from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from app_support.cli import preparse_config_path
from app_support.logging_utils import (
    configure_logging,
    enable_faulthandler,
    install_exception_logging,
)
from app_support.threading_utils import start_daemon_thread
from player_core.file_channel import append_command, read_paused_state

from .clip_loader import ClipLoadController
from .clip_renderer import ClipRenderController
from .clip_runtime import ClipCacheStore, DecodeRequestState
from .clip_selection import ClipSelectionController
from .clip_sequence import ClipSequenceController
from .lifecycle import GenauLifecycleController
from .notifier import GenauNotifier
from .pygame_view import PygameView
from .refresh_controller import GenauRefreshController
from .broker_handoff import broker_cmd_file_for_mode
from .config import load_config
from .engine import PlaybackEngine
from .state import SharedState, udp_reader
from .video import cache_dir_for_clips_folder, load_clip_frames, scan_clips
from .weird import move_clip_to_weird, weird_dir_for_clips_folder


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
    ap.add_argument("--drive-file", default=None,
                    help="Where to publish the drive readout for Nau to draw in Hybrid")
    ap.add_argument("--start-clip", default=None,
                    help="Open on this clip rather than the top of the folder — how "
                         "an orchestrator resumes the clip its last session left up")
    ap.add_argument("--tcode-udp-host", default=config.genau.tcode_udp_host)
    ap.add_argument("--tcode-udp-port", type=int, default=config.genau.tcode_udp_port)
    ap.add_argument(
        "--fun-time", action="store_true", default=False,
        help="Running under Fun Time (orchestrator owns broker handoff, suppresses voice, space pauses only)",
    )
    ap.add_argument(
        "--taskbar-identity", default=None,
        help="Group this window under an orchestrator's taskbar button instead of "
             "Genau's own; the orchestrator passes its own AppUserModelID.  "
             "Standalone, Genau is its own application",
    )
    return ap


def _name_this_process(project_dir) -> None:
    """Leave ``launch.vbs`` an interpreter that says "Genau" next time.

    Windows takes what it shows about a process from the file it was started
    from, so a plain ``pythonw.exe`` puts Genau in the task list as one more
    anonymous "Python" -- indistinguishable from Nau, which shares this venv.

    Naming this process on the way in is the one thing that cannot be done:
    writing the copy takes the very interpreter being named.  So each run makes
    it for the run after and the launcher picks it up.  Under Fun Time it is Fun
    Time's own copy that is running instead -- Genau is one of its windows then,
    not an application the user opened -- and this still prepares the standalone
    one, which is about Genau's own shortcut rather than about who started this
    run.
    """
    try:
        from app_support.process_identity import ProcessNamer
        ProcessNamer("Genau", icon=project_dir / "genau_icon.ico").prepare_launcher("Genau")
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def main(argv: list[str] | None = None) -> int:
    config = load_config(_preparse_config(argv))
    _name_this_process(config.project_dir)

    # Before any window creation, so this window is grouped under the right
    # taskbar button instead of inheriting the interpreter's.  An orchestrator
    # that passes its own identity is saying these windows are its own: under Fun
    # Time, Genau is not an application the user launched but one window of the
    # one they did.  Told one, Genau takes it and stamps nothing — the pinned
    # shortcut behind that identity belongs to whoever owns it.  Standalone there
    # is nobody to say, so Genau is its own application as before.
    identity = _preparse_taskbar_identity(argv)
    if identity:
        try:
            from player_core.taskbar import set_app_user_model_id
            set_app_user_model_id(identity)
        except Exception:
            pass  # Cosmetic: costs the icon, never worth failing to start over.
    else:
        from .win32 import APP_USER_MODEL_ID, take_taskbar_identity
        take_taskbar_identity(
            APP_USER_MODEL_ID, include="genau", exclude="genauvr",
            config_path=config.config_path,
        )

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

    # A thread, so the decode overlaps pygame init and the controller wiring
    # below rather than running before them.
    first_clip_path = clip_sequence.current_path
    preload_result: dict = {"frames": None}

    def _preload_first_clip() -> None:
        try:
            preload_result["frames"] = load_clip_frames(first_clip_path, cache_dir)
        except Exception:
            logger.warning("Failed to pre-load first clip %s", first_clip_path, exc_info=True)

    preload_thread = threading.Thread(
        target=_preload_first_clip, daemon=True, name="genau-preload",
    )
    preload_thread.start()

    view = PygameView(
        width=args.width,
        height=args.height,
        x=args.x,
        y=args.y,
        icon_path=config.project_dir / "genau_icon.ico",
        hybrid_title="Hybrid Nau+Genau",
        hybrid_icon_path=config.project_dir / "hybrid_icon.ico",
        # Borderless only under Fun Time, which owns the slot's geometry; run
        # standalone the window keeps its chrome so it can be moved and closed.
        borderless=args.fun_time,
    )

    state = SharedState()
    stop_event = threading.Event()

    start_daemon_thread(
        target=udp_reader,
        args=(args.udp_host, args.udp_port, state, stop_event, logger),
        name="genau-udp",
    )

    clip_store = ClipCacheStore(limit=args.clip_cache_size)

    engine = PlaybackEngine(last_tick=time.monotonic())

    rh_paused = {"value": False}
    hud_state = {"active": False}
    # Genau paints its clips unless something tells it otherwise: standalone it
    # owns its window outright, and an orchestrator that hides Genau in some of
    # its modes asserts DISPLAY_OFF/DISPLAY_ON as those modes change.  Defaulting
    # dark instead would make a bare `python -m genau` come up black.
    display_state = {"active": True}

    from .clip_advance import ClipAdvanceState
    from player_core.cruise_control import CruiseControlState
    from player_core.direct_control import DirectControlState, bpm_for_speed
    from player_core.tcode import UdpTCodeSink

    from .tcode import RateLimitedTCodeSender
    direct_state = DirectControlState(
        playing=False,
        speed=50,
        bpm=bpm_for_speed(50),
    )
    cruise_control = CruiseControlState()
    clip_advance = ClipAdvanceState()
    sink = UdpTCodeSink(host=args.tcode_udp_host, port=args.tcode_udp_port)
    tcode_sender = RateLimitedTCodeSender(
        sink, direct_state=direct_state, cruise=cruise_control)
    logger.info("T-Code via UDP to %s:%s", args.tcode_udp_host, args.tcode_udp_port)

    if config.voice is not None and not args.fun_time:
        from .voice import VOICE_AVAILABLE, VOICE_COMMANDS, VoiceListener
        if VOICE_AVAILABLE:
            voice_listener = VoiceListener(
                commands=VOICE_COMMANDS,
                cmd_file=command_file,
                model_path=config.voice.model_path,
                confidence_threshold=config.voice.confidence_threshold,
                device_index=config.voice.device_index,
                sample_rate=config.voice.sample_rate,
            )
            start_daemon_thread(
                target=voice_listener.run,
                name="genau-voice",
            )
            logger.info("Voice control enabled (model=%s)", config.voice.model_path)

    load_state = DecodeRequestState()
    prefetch_state = DecodeRequestState()
    notifier = GenauNotifier(args.notify_host, args.notify_port)

    renderer = ClipRenderController(
        clip_store=clip_store,
        display_frame_fn=view.display_frame,
    )

    loader = ClipLoadController(
        clip_store=clip_store,
        load_state=load_state,
        prefetch_state=prefetch_state,
        current_clip_path_getter=lambda: renderer.current_clip_path,
        decode_clip=lambda path: load_clip_frames(path, cache_dir),
        start_thread=start_daemon_thread,
        logger=logger,
        on_active_clip_loaded=renderer.prepare_active_clip_for_current_size,
    )
    weird_dir = weird_dir_for_clips_folder(clips_folder)
    selection = ClipSelectionController(
        sequence=clip_sequence,
        clip_store=clip_store,
        loader=loader,
        renderer=renderer,
        notifier=notifier,
        discard_clip=lambda path: _condemn_clip(path, weird_dir, logger),
    )

    def _reorder_clips(recent: bool) -> None:
        """Rescan the clips folder and browse it newest-first, or reshuffled.

        The rescan is half the point: clips arrive in that folder while a
        session runs, and this is the only way into the sequence short of
        launching again.  The lock is deliberately left alone — it holds whatever is on screen, and
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

    refresh_controller = GenauRefreshController(
        state=state,
        loader=loader,
        notifier=notifier,
        renderer=renderer,
        selection=selection,
        engine=engine,
        rh_paused=rh_paused,
        command_file=command_file,
        paused_file=paused_file,
        beats_per_loop=args.beats_per_loop,
        bpm_smoothing=args.bpm_smoothing,
        sync_strength=args.sync_strength,
        set_loading_text=view.set_loading_text,
        logger=logger,
        read_paused_state=read_paused_state,
        direct_state=direct_state,
        tcode_sender=tcode_sender,
        cruise_control=cruise_control,
        clip_advance=clip_advance,
        broker_cmd_file=broker_cmd_file_for_mode(config.broker_cmd_file, fun_time=args.fun_time),
        # Named by whoever launched us when there is one: standalone this is our
        # own state dir, but under Fun Time the reader is Nau, which is told the
        # path by Fun Time and must be told the same one.
        drive_file=Path(args.drive_file) if args.drive_file else config.genau_drive_file,
        console_file=Path(args.console_file) if args.console_file else None,
        set_console=view.set_console,
        present_scene=view.present,
        stop_event=stop_event,
        hud_state=hud_state,
        set_hud_mode=view.set_hud_mode,
        set_blank=view.set_blank,
        display_state=display_state,
        set_volume=view.set_volume,
        reorder_clips=_reorder_clips,
    )
    from .clip_advance import toggle_lock
    from player_core.cruise_control import toggle_cruise_control
    from player_core.direct_control import (
        adjust_amplitude,
        adjust_center,
        adjust_speed,
        cycle_shape,
        space_action,
        toggle_playing,
    )

    dashboard_cmd_file = Path(args.dashboard_cmd_file) if args.dashboard_cmd_file else None

    def _post_console(command: str) -> None:
        """Ask Fun Time for what the console just said, on the same channel its
        dashboard uses, so it is routed like any other command.  Inert with no
        dashboard (standalone), where there is nowhere to ask."""
        if command and dashboard_cmd_file is not None:
            append_command(dashboard_cmd_file, command)

    def _press_console(mx: int, my: int) -> None:
        """A press on what Genau draws over its clip — the volume chip, a console
        button's own command, or the level the drive readout's bar under the
        pointer is set to.

        The chip is tried first: it floats in its own corner, so a press on it is
        never also a press on the panel.
        """
        volume = view.press_volume_at(mx, my)
        if volume:
            _post_console(volume)
            return
        _post_console(view.console_press_at(mx, my))

    def _drag_console(mx: int, my: int) -> None:
        """The pointer moving with the button down: a bar the press took hold of
        goes on being set, and says nothing while its level has not moved."""
        _post_console(view.console_drag_to(mx, my))

    lifecycle = GenauLifecycleController(
        renderer=renderer,
        selection=selection,
        stop_event=stop_event,
        notifier=notifier,
        resize_delay_ms=config.genau.resize_debounce_ms,
        dashboard_cmd_file=dashboard_cmd_file,
        quarter_offset=lambda: engine.__setattr__("phase", (engine.phase + 0.25) % 1.0),
        on_toggle_playing=lambda: toggle_playing(direct_state),
        on_pause_playing=lambda: space_action(direct_state, pause_only=args.fun_time),
        on_adjust_speed=lambda delta: adjust_speed(direct_state, delta),
        on_adjust_amplitude=lambda delta: adjust_amplitude(direct_state, delta),
        on_adjust_center=lambda delta: adjust_center(direct_state, delta),
        on_cycle_shape=lambda: cycle_shape(direct_state),
        on_toggle_cruise=lambda: toggle_cruise_control(cruise_control),
        on_toggle_lock=lambda: toggle_lock(clip_advance),
        on_weird_clip=selection.discard_current,
        on_console_press=_press_console,
        on_console_drag=_drag_console,
        on_console_release=view.console_release,
        on_console_motion=view.set_console_hover,
    )

    logger.info("Loaded %s clips from %s", selection.count, clips_folder)
    preload_thread.join(timeout=10.0)
    if preload_result["frames"] is not None:
        clip_store.clip_cache[first_clip_path] = {"frames": preload_result["frames"]}
        logger.info("Pre-loaded %d frames for %s", len(preload_result["frames"]), first_clip_path.name)
    selection.set_current_clip(selection.current_path)

    while not stop_event.is_set():
        lifecycle.process_events()
        refresh_controller.refresh()
        view.clock.tick(120)

    tcode_sender.close()
    view.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
