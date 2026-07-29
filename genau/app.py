from __future__ import annotations

import argparse
import logging
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
    ap.add_argument("--render-batch", type=int, default=config.genau.render_batch)
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
    ap.add_argument("--tcode-udp-host", default=config.genau.tcode_udp_host)
    ap.add_argument("--tcode-udp-port", type=int, default=config.genau.tcode_udp_port)
    ap.add_argument(
        "--fun-time", action="store_true", default=False,
        help="Running under Fun Time (orchestrator owns broker handoff, suppresses voice, space pauses only)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    config = load_config(_preparse_config(argv))

    # Before any window creation, so Genau gets its own taskbar identity
    # (icon + title) instead of inheriting python.exe's.
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
    clip_sequence = ClipSequenceController(clips)
    cache_dir = cache_dir_for_clips_folder(clips_folder)

    # Start decoding the first clip immediately in a background thread.
    # This overlaps with pygame init + controller wiring below, so by
    # the time the main loop starts the first clip is likely already
    # decoded and ready to display.
    first_clip_path = clip_sequence.current_path
    preload_result: dict = {"frames": None}

    def _preload_first_clip() -> None:
        try:
            preload_result["frames"] = load_clip_frames(first_clip_path, cache_dir)
        except Exception:
            logger.warning("Failed to pre-load first clip %s", first_clip_path, exc_info=True)

    preload_thread = None
    if first_clip_path is not None:
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
    from .cruise_control import CruiseControlState
    from .direct_control import DirectControlState, bpm_for_speed
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
    tcode_sender = RateLimitedTCodeSender(sink, direct_state=direct_state)
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
        logger=logger,
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
        on_error=lambda msg: state.__setattr__("error", msg),
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
        show_window=lambda: None,
        hide_window=lambda: None,
        set_loading_text=view.set_loading_text,
        logger=logger,
        log_name=config.log_file("genau_listener").name,
        read_paused_state=read_paused_state,
        direct_state=direct_state,
        tcode_sender=tcode_sender,
        cruise_control=cruise_control,
        clip_advance=clip_advance,
        broker_cmd_file=broker_cmd_file_for_mode(config.broker_cmd_file, fun_time=args.fun_time),
        # Named by whoever launched us when there is one: standalone this is our
        # own state dir, but under Fun Time the reader is Nau, which is told the
        # path by Fun Time — and Genau resolving its own put the readout in a
        # directory nobody was watching, so Hybrid drew no readout at all.
        drive_file=Path(args.drive_file) if args.drive_file else config.genau_drive_file,
        console_file=Path(args.console_file) if args.console_file else None,
        set_console=view.set_console,
        present_scene=view.present,
        stop_event=stop_event,
        hud_state=hud_state,
        set_hud_mode=view.set_hud_mode,
        set_blank=view.set_blank,
        display_state=display_state,
    )
    from .clip_advance import toggle_lock
    from .cruise_control import toggle_cruise_control
    from .direct_control import (
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
        """A press on the console Genau is drawing — a button's own command, or
        the level the drive readout's bar under the pointer is set to."""
        _post_console(view.console_press_at(mx, my))

    def _drag_console(mx: int, my: int) -> None:
        """The pointer moving with the button down: a bar the press took hold of
        goes on being set, and says nothing while its level has not moved."""
        _post_console(view.console_drag_to(mx, my))

    lifecycle = GenauLifecycleController(
        view=view,
        renderer=renderer,
        selection=selection,
        stop_event=stop_event,
        notifier=notifier,
        resize_delay_ms=config.genau.resize_debounce_ms,
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
    if preload_thread is not None:
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
