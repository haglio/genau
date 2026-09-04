"""GenauVR — VR180 clip player with OSR2 T-Code sync.

Features: voice commands, cruise control, VR controller pitch adjust.
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path
from typing import IO

from app_support.logging_utils import (
    configure_logging,
    enable_faulthandler,
    install_exception_logging,
)

from . import vr_runtime
from .audio import AudioPlayer
from .carousel import ClipCarousel
from .clip import load_clip
from .config import DEFAULT_CONFIG, VrConfig, clips_to_play, load_config
from .cruise_control import CruiseControlState
from .loop import controls_for, run_loop
from .playback import (
    PlaybackEngine,
    RateLimitedTCodeSender,
    RobotHandState,
    UdpTCodeSink,
    WaveformShape,
)

logger = logging.getLogger(__name__)


ICON_FILE = Path(__file__).resolve().parent.parent / "genau_vr_icon.ico"


def _show_error_popup(message: str) -> None:
    """Say why GenauVR could not start, in the family's colors under its own
    icon.  Qt is imported here because this is the only window it ever draws."""
    from shared_ui.alert import show_alert

    show_alert("GenauVR", message, icon=ICON_FILE)


def _configure_logging() -> tuple[logging.Logger, IO[str]]:
    """Send this run's log to a file, and return the crash log to hold open.

    Under ``pythonw`` — how the shortcut always starts us — ``sys.stderr`` is
    ``None``, so anything logged to a stream is discarded and a failed startup
    leaves no trace at all. The file is the only record there is.

    It goes to the default state directory rather than the configured one, so
    that a config which cannot be read still gets its failure written down.
    """
    state_dir = DEFAULT_CONFIG.parent / "state"
    log = configure_logging("genau_vr", state_dir / "genau_vr.log")
    install_exception_logging(log)
    fault_fp = enable_faulthandler(state_dir / "genau_vr_crash.log")
    return log, fault_fp


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GenauVR — VR180 clip player")
    parser.add_argument("clip", nargs="?", help="Path to a video clip")
    parser.add_argument("--speed", type=int, default=50, help="Playback speed 0-100 (default: 50)")
    parser.add_argument("--config", default=None, help="Path to genau_config.json")
    parser.add_argument("--no-voice", action="store_true", help="Disable voice control")
    return parser.parse_args(argv)


def _start_voice(config: VrConfig, cmd_file: Path) -> None:
    """Start voice listener thread if vosk is available."""
    from .voice import VOICE_AVAILABLE, VOICE_COMMANDS, VoiceListener

    if not VOICE_AVAILABLE:
        logger.info("Voice control unavailable (install vosk + sounddevice)")
        return

    listener = VoiceListener(
        commands=VOICE_COMMANDS,
        cmd_file=cmd_file,
        model_path=config.voice.model_path,
        confidence_threshold=config.voice.confidence_threshold,
        device_index=config.voice.device_index,
        sample_rate=config.voice.sample_rate,
    )
    thread = threading.Thread(target=listener.run, daemon=True, name="voice")
    thread.start()
    logger.info("Voice control started")


def _consume_command_file(cmd_file: Path) -> str | None:
    """Read and delete the command file if it exists."""
    if not cmd_file.exists():
        return None
    try:
        text = cmd_file.read_text(encoding="utf-8").strip()
        cmd_file.unlink(missing_ok=True)
        return text or None
    except OSError:
        return None


VR_APP_USER_MODEL_ID = "GenauVR.App"


def _name_this_process() -> None:
    """Leave ``launch_vr.vbs`` an interpreter that says "Genau VR" next time.

    Windows takes what it shows about a process from the file it was started
    from, so a plain ``pythonw.exe`` puts GenauVR in the task list as one more
    anonymous "Python", beside the two housemates that share this venv.  Naming
    this process on the way in is the one thing that cannot be done -- writing
    the copy takes the interpreter being named -- so each run makes it for the
    run after and the launcher picks it up.
    """
    try:
        from app_support.process_identity import ProcessNamer
        ProcessNamer("Genau VR", icon=ICON_FILE).prepare_launcher("GenauVR")
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def main(argv: list[str] | None = None) -> None:
    """Start GenauVR, or say on screen why it could not start.

    Every path out of startup ends either in the VR loop or in a dialog: a
    hidden-launched process that just exits is indistinguishable from a crash.
    That has to include opening the log, which runs before there is a log to
    write the failure to -- so it gets a dialog of its own and startup stops
    there.  An install whose ``state/`` will not take a log file will not take
    the command files a session runs on either.
    """
    try:
        log, fault_fp = _configure_logging()
    except Exception as exc:
        _show_error_popup(
            f"GenauVR could not start.\n\n"
            f"It could not open its log in the install's state folder.\n\n"
            f"Detail: {exc}"
        )
        return
    _name_this_process()
    runtime_was_up = vr_runtime.runtime_was_running()  # before _start's ensure_ready() moves it
    try:
        _start(argv)
    except Exception as exc:
        log.exception("GenauVR failed to start")
        _show_error_popup(f"GenauVR could not start.\n\nDetail: {exc}")
    finally:
        if not runtime_was_up:
            log.info("Stopping the VR runtime this session started")
            vr_runtime.stop_runtime()
        fault_fp.close()


def _start(argv: list[str] | None) -> None:
    args = _parse_args(argv)

    # Before any window creation, so GenauVR gets its own taskbar identity
    # instead of inheriting python.exe's.  Needs the args first, because whether
    # this session is the app the pin launches is a question about its config.
    from genau.win32 import take_taskbar_identity
    take_taskbar_identity(
        VR_APP_USER_MODEL_ID, include="genauvr",
        config_path=args.config or DEFAULT_CONFIG,
    )

    config = load_config(Path(args.config) if args.config else None)

    # Ask for VR before decoding anything: a clip takes seconds to load, and
    # spending them only to discover there is no headset delays the dialog
    # that explains it — and flashes a window on the way there.
    vr = vr_runtime.ensure_ready()
    if vr.readiness is not vr_runtime.Readiness.READY:
        logger.error("VR not available: %s", vr.readiness.value)
        _show_error_popup(vr_runtime.explain(vr))
        return

    clip_list = clips_to_play(args.clip, config)
    tcode_host, tcode_port = config.tcode_endpoint

    logger.info("Found %d clip(s)", len(clip_list))
    logger.info("Loading clip: %s", clip_list[0])
    frames = load_clip(clip_list[0])
    logger.info("Loaded %d frames (%dx%d)", len(frames), frames[0].shape[1], frames[0].shape[0])

    from .vr_renderer import VRRenderer
    from .vr_session import VRSession

    logger.info("Initializing VR session...")
    try:
        session = VRSession()
        renderer = VRRenderer()
    except Exception as exc:
        logger.error("VR initialization failed: %s", exc)
        _show_error_popup(
            f"Could not start VR session.\n\n"
            f"The headset answered, but GenauVR could not open a session on it.\n\n"
            f"Error: {exc}"
        )
        return

    audio = AudioPlayer()
    audio.load_for_clip(clip_list[0])

    state = RobotHandState(playing=True, speed=args.speed, shape=WaveformShape.SINE)
    engine = PlaybackEngine(last_tick=time.monotonic())
    cruise = CruiseControlState()
    tcode_sink = UdpTCodeSink(tcode_host, tcode_port)
    tcode_sender = RateLimitedTCodeSender(tcode_sink, robot_hand=state)

    cmd_file = config.state_dir / "genau_vr_cmd.txt"

    if not args.no_voice:
        _start_voice(config, cmd_file)

    stop_event = threading.Event()

    logger.info(
        "Entering VR loop (speed=%d, BPM=%.1f, tcode=%s:%d)",
        state.speed, state.bpm, tcode_host, tcode_port,
    )

    try:
        carousel = ClipCarousel(clip_list, frames, audio=audio)
        run_loop(
            session, renderer, engine,
            controls_for(carousel, engine, state, cruise, audio, stop_event),
            carousel, tcode_sender, cmd_file, _consume_command_file,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        tcode_sender.close()
        audio.close()
        renderer.close()
        session.close()
        logger.info("Shutdown complete")
