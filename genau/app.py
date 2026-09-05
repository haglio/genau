from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from app_support.cli import preparse_config_path
from app_support.logging_utils import (
    configure_logging,
    enable_faulthandler,
    install_exception_logging,
)
from app_support.threading_utils import start_daemon_thread
from app_support.win32 import set_app_user_model_id
from player_core.broker_feed import BrokerFeed, udp_reader
from player_core.clip_advance import ClipAdvanceState
from player_core.clip_cache import ClipCacheStore, DecodeRequestState
from player_core.clip_decode import load_clip_frames
from player_core.clip_folder import (
    cache_dir_for_clips_folder,
    move_clip_to_weird,
    scan_clips,
    weird_dir_for_clips_folder,
)
from player_core.clip_loader import ClipLoadController
from player_core.clip_preload import FirstClipPreload
from player_core.clip_renderer import ClipRenderController
from player_core.clip_selection import ClipSelectionController
from player_core.clip_sequence import ClipSequenceController
from player_core.cruise_control import CruiseControlState
from player_core.file_channel import read_paused_state
from player_core.flag import Flag
from player_core.genau_controls import GenauControls
from player_core.genau_notifier import GenauNotifier
from player_core.genau_refresh import GenauRefreshController
from player_core.robot_hand import (
    RobotHandState,
    bpm_for_speed,
    pause_playing,
    toggle_playing,
)
from player_core.robot_hand_beat import BeatEngine
from player_core.robot_hand_driver import RobotHandTCodeDriver
from player_core.tcode import UdpTCodeSink

from .config import load_config
from .console_pointer import ConsolePointer
from .lifecycle import GenauLifecycleController
from .pygame_view import PygameView


def _preparse_config(argv: list[str] | None) -> str | None:
    return preparse_config_path(argv)


def _preparse_taskbar_identity(argv: list[str] | None) -> str | None:
    """The ``--taskbar-identity`` an orchestrator passed, read before the parser.

    The identity has to be claimed before any window exists and the full parser
    needs the loaded config, so this one flag is read off argv the way
    ``--config`` is.  Only the exact spellings argparse itself accepts, so a
    value that happens to contain the flag's name cannot be mistaken for it.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    for index, arg in enumerate(args):
        if arg == "--taskbar-identity":
            return args[index + 1] if index + 1 < len(args) else None
        if arg.startswith("--taskbar-identity="):
            return arg.split("=", 1)[1]
    return None


def _condemn_clip(path: Path, weird_dir: Path, logger: logging.Logger) -> None:
    """Move a clip out of rotation, logging where it went — or why it didn't.

    A failed move must not take the player down with it: the clip is already
    off the playlist by the time this runs, so the worst case is a file left
    in ``clips/`` that the next session shows again.
    """
    try:
        landed = move_clip_to_weird(path, weird_dir)
    except OSError:
        logger.warning("Could not move %s to %s", path.name, weird_dir, exc_info=True)
        return
    if landed is None:
        logger.info("Clip %s was already gone; nothing to condemn", path.name)
    else:
        logger.info("Condemned %s to %s", path.name, weird_dir)


def build_parser(config) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Genau clip player.")
    ap.add_argument("--config", help="Path to a JSON config file.")
    ap.add_argument("--clips-folder", default=str(config.clips_dir))
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--beats-per-loop", type=float, default=config.genau.beats_per_loop)
    ap.add_argument("--clip-cache-size", type=int, default=config.genau.clip_cache_size)
    ap.add_argument("--bpm-smoothing", type=float, default=config.genau.bpm_smoothing)
    ap.add_argument("--sync-strength", type=float, default=config.genau.sync_strength)
    ap.add_argument("--udp-host", default=config.genau.udp_host)
    ap.add_argument("--udp-port", type=int, default=config.genau.udp_port)
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--notify-host", default=config.genau.notify_host)
    ap.add_argument("--notify-port", type=int, default=config.genau.notify_port)
    ap.add_argument("--command-file", default=str(config.genau_cmd_file))
    ap.add_argument("--paused-file", default=str(config.genau_paused_file))
    ap.add_argument("--console-file", default=None,
                    help="Poll this file for the console panel Fun Time publishes")
    ap.add_argument("--dashboard-cmd-file", default=None,
                    help="Where a press on the console posts its Fun Time command")
    ap.add_argument("--drive-file", default=str(config.genau_drive_file),
                    help="Where to publish the drive readout for Nau to draw in video mode")
    ap.add_argument("--status-file", default=None,
                    help="Where to publish what the hand is doing; defaults to "
                         "beside the command file, which is where it has always gone")
    ap.add_argument("--start-clip", default=None,
                    help="Open on this clip rather than the top of the folder — how "
                         "an orchestrator resumes the clip its last session left up")
    ap.add_argument("--tcode-udp-host", default=config.genau.tcode_udp_host)
    ap.add_argument("--tcode-udp-port", type=int, default=config.genau.tcode_udp_port)
    ap.add_argument(
        "--taskbar-identity", default=None,
        help="Group this window under Fun Time's taskbar button: its AppUserModelID",
    )
    ap.add_argument("--icon", default=None,
                    help="The window icon Fun Time hands over, so an Alt-Tab entry "
                         "says whose window this is")
    return ap


def main(argv: list[str] | None = None) -> int:
    config = load_config(_preparse_config(argv))

    # Before any window creation, so this window is grouped under Fun Time's
    # taskbar button instead of the interpreter's: Genau is one window of the
    # application the user launched, not an application of its own.
    identity = _preparse_taskbar_identity(argv)
    if identity:
        try:
            set_app_user_model_id(identity)
        except OSError:
            pass  # Cosmetic: costs the icon, never worth failing to start over.

    logger = configure_logging("genau", config.log_file("genau_listener"))
    install_exception_logging(logger)
    fault_fp = enable_faulthandler(config.log_file("genau_crash"))
    args = build_parser(config).parse_args(argv)

    logger.info("Genau starting (pid=%d)", __import__("os").getpid())
    try:
        rc = run_listener(args, config, logger)
        logger.info("Genau exiting normally (rc=%d)", rc)
        return rc
    except KeyboardInterrupt:
        logger.info("Genau interrupted by user")
        return 0
    except Exception:
        logger.critical("Genau crashed in main", exc_info=True)
        raise
    finally:
        try:
            fault_fp.close()
        except Exception:
            pass


@dataclass(frozen=True)
class DriveStack:
    """What Genau drives the device with: the hand, what varies it, what moves
    the clip on, and the sender that puts it on the wire."""

    robot_hand: RobotHandState
    cruise_control: CruiseControlState
    clip_advance: ClipAdvanceState
    tcode_sender: RobotHandTCodeDriver


def _build_drive_stack(args, logger: logging.Logger) -> DriveStack:
    """One hand, one cruise stack, one clip advance, one sender.

    Built together because they are one thing wired four ways: the sender reads
    the hand and the stack, the readout draws all three, and a second copy of
    any of them would leave a key moving one while the picture follows another.
    """
    robot_hand = RobotHandState(playing=False, speed=50, bpm=bpm_for_speed(50))
    cruise_control = CruiseControlState()
    sink = UdpTCodeSink(host=args.tcode_udp_host, port=args.tcode_udp_port)
    logger.info("T-Code via UDP to %s:%s", args.tcode_udp_host, args.tcode_udp_port)
    return DriveStack(
        robot_hand=robot_hand,
        cruise_control=cruise_control,
        clip_advance=ClipAdvanceState(),
        tcode_sender=RobotHandTCodeDriver(
            sink, robot_hand=robot_hand, cruise=cruise_control),
    )


@dataclass(frozen=True)
class ClipPipeline:
    """The three parts that get a clip from the folder onto the screen: what
    decodes, what draws, and what decides which one."""

    renderer: ClipRenderController
    loader: ClipLoadController
    selection: ClipSelectionController


def _build_clip_pipeline(
    clip_sequence, clip_store, view, notifier, clips_folder: Path,
    cache_dir: Path, logger: logging.Logger,
) -> ClipPipeline:
    renderer = ClipRenderController(
        clip_store=clip_store,
        blit_frame=view.blit_frame,
    )
    loader = ClipLoadController(
        clip_store=clip_store,
        load_state=DecodeRequestState(),
        prefetch_state=DecodeRequestState(),
        current_clip_path_getter=lambda: renderer.current_clip_path,
        decode_clip=lambda path: load_clip_frames(path, cache_dir),
        start_thread=start_daemon_thread,
        logger=logger,
        on_active_clip_loaded=renderer.prepare_active_clip_for_current_size,
    )
    weird_dir = weird_dir_for_clips_folder(clips_folder)
    return ClipPipeline(
        renderer=renderer,
        loader=loader,
        selection=ClipSelectionController(
            sequence=clip_sequence,
            clip_store=clip_store,
            loader=loader,
            renderer=renderer,
            notifier=notifier,
            condemn_clip=lambda path: _condemn_clip(path, weird_dir, logger),
        ),
    )


def _reorder_clips(
    clips_folder: Path, config, selection, logger: logging.Logger, recent: bool,
) -> None:
    """Rescan the clips folder and browse it newest-first, or reshuffled.

    The rescan is half the point: clips arrive in that folder while a session
    runs, and this is the only way into the sequence short of launching again.
    The lock is deliberately left alone — it holds whatever is on screen, and
    after this that is the head of the order just asked for.

    A folder that scanned to nothing keeps the sequence already loaded rather
    than taking Genau's picture away; :func:`scan_clips` says so by raising.
    """
    try:
        clips = scan_clips(
            clips_folder,
            shuffle_on_load=config.genau.shuffle_on_load,
            recent=recent,
        )
    except (OSError, RuntimeError):
        logger.warning("Could not rescan %s; keeping the sequence", clips_folder,
                       exc_info=True)
        return
    selection.reorder(clips)
    logger.info("Browsing %s (%d clips)",
                "newest-first" if recent else "reshuffled", len(clips))


def run_listener(args, config, logger: logging.Logger) -> int:
    command_file = Path(args.command_file)
    paused_file = Path(args.paused_file)

    clips_folder = Path(args.clips_folder)
    if not clips_folder.exists():
        raise RuntimeError(f"Clips folder does not exist: {clips_folder}")

    clips = scan_clips(clips_folder, shuffle_on_load=config.genau.shuffle_on_load)
    # Open on the clip the last session was left showing, when an orchestrator
    # names one.  Before the preload below, so the clip that gets decoded ahead
    # of the window is the one that will actually be on screen.
    clip_sequence = ClipSequenceController(
        clips, start_at=Path(args.start_clip) if args.start_clip else None,
    )
    cache_dir = cache_dir_for_clips_folder(clips_folder)

    # Started here, so the decode overlaps pygame init and the controller wiring
    # below rather than running before them.
    first_clip_path = clip_sequence.current_path
    preload = FirstClipPreload(
        first_clip_path, lambda path: load_clip_frames(path, cache_dir), logger)
    preload.start()

    view = PygameView(
        width=args.width,
        height=args.height,
        x=args.x,
        y=args.y,
        icon_path=Path(args.icon) if args.icon else None,
        video_title="Video Nau+Genau",
    )

    broker = BrokerFeed()
    stop_event = threading.Event()

    start_daemon_thread(
        target=udp_reader,
        args=(args.udp_host, args.udp_port, broker, stop_event, logger),
        name="genau-udp",
    )

    dashboard_cmd_file = Path(args.dashboard_cmd_file) if args.dashboard_cmd_file else None

    clip_store = ClipCacheStore(limit=args.clip_cache_size)

    # One clock for the whole frame loop, so the tick and the window cannot
    # disagree about what time it is within a turn.
    clock = time.monotonic
    engine = BeatEngine(last_tick=clock())

    paused = Flag()
    hud = Flag()

    drive = _build_drive_stack(args, logger)

    notifier = GenauNotifier(args.notify_host, args.notify_port)
    pipeline = _build_clip_pipeline(
        clip_sequence, clip_store, view, notifier, clips_folder, cache_dir, logger)
    renderer, loader, selection = (
        pipeline.renderer, pipeline.loader, pipeline.selection)

    # Everything a command, a key or a console press can move, in one place: the
    # tick drains commands into it and the window's keys move the same object,
    # so the two paths into a control cannot drift apart.
    controls = GenauControls(
        engine=engine,
        paused=paused,
        step_clip=selection.step,
        condemn_clip=selection.condemn_current,
        robot_hand=drive.robot_hand,
        cruise_control_state=drive.cruise_control,
        set_stroke_phase=drive.tcode_sender.set_stroke_phase,
        clip_advance_state=drive.clip_advance,
        stop_event=stop_event,
        hud=hud,
        set_volume=view.set_volume,
        reorder_clips=partial(_reorder_clips, clips_folder, config, selection, logger),
    )

    refresh_controller = GenauRefreshController(
        controls=controls,
        broker=broker,
        loader=loader,
        notifier=notifier,
        renderer=renderer,
        selection=selection,
        command_file=command_file,
        paused_file=paused_file,
        beats_per_loop=args.beats_per_loop,
        bpm_smoothing=args.bpm_smoothing,
        sync_strength=args.sync_strength,
        set_loading_text=view.set_loading_text,
        logger=logger,
        now_source=clock,
        read_paused_state=read_paused_state,
        tcode_sender=drive.tcode_sender,
        status_file=Path(args.status_file) if args.status_file else None,
        # Named by Fun Time, whose Nau is told the same path.
        drive_file=Path(args.drive_file),
        console_file=Path(args.console_file) if args.console_file else None,
        set_console=view.set_console,
        present_scene=view.present,
        set_hud_mode=view.set_hud_mode,
    )
    lifecycle = GenauLifecycleController(
        renderer=renderer,
        controls=controls,
        resize_delay_ms=config.genau.resize_debounce_ms,
        now_source=clock,
        dashboard_cmd_file=dashboard_cmd_file,
        on_toggle_playing=lambda: toggle_playing(drive.robot_hand),
        on_pause_playing=lambda: pause_playing(drive.robot_hand),
        console_pointer=ConsolePointer(view, dashboard_cmd_file),
    )

    logger.info("Loaded %s clips from %s", selection.count, clips_folder)
    frames = preload.wait()
    if frames is not None:
        clip_store.clip_cache[first_clip_path] = {"frames": frames}
        logger.info("Pre-loaded %d frames for %s", len(frames), first_clip_path.name)
    selection.set_current_clip(selection.current_path)

    while not stop_event.is_set():
        lifecycle.process_events()
        refresh_controller.refresh()
        view.clock.tick(120)

    drive.tcode_sender.close()
    view.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
