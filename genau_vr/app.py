"""GenauVR — VR180 clip player with OSR2 T-Code sync.

Features: voice commands, cruise control, VR controller pitch adjust.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import IO

import numpy as np

from app_support.logging_utils import (
    configure_logging,
    enable_faulthandler,
    install_exception_logging,
)

from . import vr_runtime
from .clip import load_clip, scan_clips
from .cruise_control import CruiseControlState, tick_cruise_control
from .playback import (
    DirectControlState,
    PlaybackEngine,
    RateLimitedTCodeSender,
    UdpTCodeSink,
    WaveformShape,
    display_index_for_phase,
    display_phase_for_position,
    update_engine,
)
from .projection import fov_to_projection_matrix, pose_to_view_matrix
from .runtime_commands import apply_runtime_command

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "genau_config.json"


def _show_error_popup(message: str) -> None:
    """Show a Win32 MessageBox error dialog.

    GenauVR is launched hidden from a shortcut, so it has no claim on the
    foreground: without these two flags the dialog opens *behind* whatever the
    user is looking at, which reads as having crashed with no explanation.
    """
    MB_OK = 0x0
    MB_ICONERROR = 0x10
    MB_SETFOREGROUND = 0x00010000
    MB_TOPMOST = 0x00040000
    ctypes.windll.user32.MessageBoxW(
        None, message, "GenauVR",
        MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST,
    )


def _state_dir(cfg: dict) -> Path:
    """The directory this install keeps its logs and command files in."""
    state_dir = Path(cfg.get("state_dir", "state"))
    if not state_dir.is_absolute():
        state_dir = DEFAULT_CONFIG.parent / state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


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


def _load_config(args: argparse.Namespace) -> dict:
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    if config_path.exists():
        with config_path.open() as f:
            return json.load(f)
    return {}


def _resolve_clip_list(args: argparse.Namespace, cfg: dict) -> list[Path]:
    if args.clip:
        p = Path(args.clip)
        if not p.exists():
            raise FileNotFoundError(f"Clip not found: {p}")
        return [p]

    vr_clips_dir = cfg.get("vr_clips_dir")
    if vr_clips_dir:
        vr_dir = Path(vr_clips_dir)
        if vr_dir.exists():
            return scan_clips(vr_dir)

    clips_dir = cfg.get("clips_dir")
    if clips_dir:
        return scan_clips(Path(clips_dir))

    raise RuntimeError("No clip specified and no clips_dir in config")


def _resolve_tcode_endpoint(cfg: dict) -> tuple[str, int]:
    genau = cfg.get("genau", {})
    return (
        genau.get("tcode_udp_host", "127.0.0.1"),
        genau.get("tcode_udp_port", 50557),
    )


def _start_voice(cfg: dict, cmd_file: Path) -> None:
    """Start voice listener thread if vosk is available."""
    from .voice import VOICE_AVAILABLE, VOICE_COMMANDS, VoiceListener

    if not VOICE_AVAILABLE:
        logger.info("Voice control unavailable (install vosk + sounddevice)")
        return

    voice_cfg = cfg.get("voice_control", {})
    listener = VoiceListener(
        commands=VOICE_COMMANDS,
        cmd_file=cmd_file,
        model_path=voice_cfg.get("model_path", "vosk-model-small-en-us-0.15"),
        confidence_threshold=voice_cfg.get("confidence_threshold", 0.7),
        device_index=voice_cfg.get("device_index"),
        sample_rate=voice_cfg.get("sample_rate", 16000),
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


class AudioPlayer:
    """Manages looping audio playback. Audio plays continuously, not synced to phase."""

    def __init__(self) -> None:
        self._initialized = False
        self._volume = 0.25
        try:
            import pygame
            pygame.init()
            from pygame._sdl2.audio import get_audio_device_names
            device = None
            for name in get_audio_device_names(False):
                if "pimax" in name.lower():
                    device = name
                    break
            pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048,
                              devicename=device)
            self._initialized = True
            logger.info("Audio mixer initialized (device=%s)", device or "default")
        except Exception:
            logger.warning("Audio mixer unavailable", exc_info=True)

    def load_for_clip(self, clip_path: Path) -> None:
        if not self._initialized:
            return
        import pygame
        self.stop()
        audio_path = self._find_audio(clip_path)
        if audio_path is None:
            logger.info("No audio found for clip: %s", clip_path.name)
            return
        try:
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play(loops=-1)
            pygame.mixer.music.set_volume(self._volume)
            logger.info("Audio playing: %s", audio_path.name)
        except Exception:
            logger.warning("Failed to load audio", exc_info=True)

    @staticmethod
    def _find_audio(clip_path: Path) -> Path | None:
        """Find matching MP3 in the audio/ sibling directory."""
        audio_dir = clip_path.parent.parent / "audio"
        mp3 = audio_dir / (clip_path.stem + ".mp3")
        if mp3.exists():
            return mp3
        return None

    def adjust_volume(self, delta: float) -> None:
        self._volume = max(0.0, min(1.0, self._volume + delta))
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.set_volume(self._volume)

    def stop(self) -> None:
        if not self._initialized:
            return
        import pygame
        pygame.mixer.music.stop()

    def close(self) -> None:
        self.stop()
        if self._initialized:
            import pygame
            pygame.mixer.quit()


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
        icon = Path(__file__).resolve().parent.parent / "genau_vr_icon.ico"
        ProcessNamer("Genau VR", icon=icon).prepare_launcher("GenauVR")
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


def main(argv: list[str] | None = None) -> None:
    """Start GenauVR, or say on screen why it could not start.

    Every path out of startup ends either in the VR loop or in a dialog: a
    hidden-launched process that just exits is indistinguishable from a crash.
    """
    log, fault_fp = _configure_logging()
    _name_this_process()
    try:
        _start(argv)
    except Exception as exc:
        log.exception("GenauVR failed to start")
        _show_error_popup(f"GenauVR could not start.\n\nDetail: {exc}")
    finally:
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

    cfg = _load_config(args)

    # Ask for VR before decoding anything: a clip takes seconds to load, and
    # spending them only to discover there is no headset delays the dialog
    # that explains it — and flashes a window on the way there.
    vr = vr_runtime.ensure_ready()
    if vr.readiness is not vr_runtime.Readiness.READY:
        logger.error("VR not available: %s", vr.readiness.value)
        _show_error_popup(vr_runtime.explain(vr))
        return

    clip_list = _resolve_clip_list(args, cfg)
    tcode_host, tcode_port = _resolve_tcode_endpoint(cfg)

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

    state = DirectControlState(playing=True, speed=args.speed, shape=WaveformShape.SINE)
    engine = PlaybackEngine(last_tick=time.monotonic())
    cruise = CruiseControlState()
    tcode_sink = UdpTCodeSink(tcode_host, tcode_port)
    tcode_sender = RateLimitedTCodeSender(tcode_sink, direct_state=state)

    cmd_file = _state_dir(cfg) / "genau_vr_cmd.txt"

    if not args.no_voice:
        _start_voice(cfg, cmd_file)

    stop_event = threading.Event()
    rh_paused: dict[str, bool] = {"value": False}

    logger.info(
        "Entering VR loop (speed=%d, BPM=%.1f, tcode=%s:%d)",
        state.speed, state.bpm, tcode_host, tcode_port,
    )

    try:
        _run_loop(session, renderer, engine, state, cruise, tcode_sender,
                  frames, clip_list, audio, cmd_file, stop_event, rh_paused)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        tcode_sender.close()
        audio.close()
        renderer.close()
        session.close()
        logger.info("Shutdown complete")


def _pitch_rotation_matrix(angle: float) -> np.ndarray:
    """Build a 4x4 rotation matrix around the X axis (pitch)."""
    c, s = math.cos(angle), math.sin(angle)
    mat = np.eye(4, dtype=np.float32)
    mat[1, 1] = c
    mat[1, 2] = -s
    mat[2, 1] = s
    mat[2, 2] = c
    return mat


def _run_loop(
    session,
    renderer,
    engine: PlaybackEngine,
    state: DirectControlState,
    cruise: CruiseControlState,
    tcode_sender: RateLimitedTCodeSender,
    frames: list[np.ndarray],
    clip_list: list[Path],
    audio: AudioPlayer,
    cmd_file: Path,
    stop_event: threading.Event,
    rh_paused: dict,
) -> None:
    import glfw

    clip_index = 0
    frame_count = len(frames)
    last_frame_idx = -1
    pitch_offset = 0.0
    last_time = time.monotonic()
    def step_clip(delta: int) -> None:
        nonlocal frames, frame_count, last_frame_idx, clip_index
        if len(clip_list) <= 1:
            return
        clip_index = (clip_index + delta) % len(clip_list)
        new_path = clip_list[clip_index]
        logger.info("Switching to clip: %s", new_path.name)
        frames = load_clip(new_path)
        frame_count = len(frames)
        last_frame_idx = -1
        engine.phase = 0.0
        audio.load_for_clip(new_path)

    while session.running and not stop_event.is_set():
        session.poll_events()
        if not session.running:
            break

        if glfw.window_should_close(session._window):
            break

        if not session.session_ready:
            glfw.poll_events()
            time.sleep(0.01)
            continue

        should_render, display_time, views = session.frame_begin()

        now = time.monotonic()
        dt = now - last_time
        last_time = now

        command = _consume_command_file(cmd_file)
        if command:
            apply_runtime_command(
                command,
                rh_paused=rh_paused,
                step_clip=step_clip,
                direct_state=state,
                cruise_control_state=cruise,
                stop_event=stop_event,
                audio_player=audio,
            )

        tick_cruise_control(state, cruise, now)

        update_engine(
            engine,
            now=now,
            auto_active=True,
            raw_bpm=state.bpm,
            beats_per_loop=1.0,
            bpm_smoothing=0.14,
            paused=not state.playing or rh_paused["value"],
        )

        tcode_sender.maybe_send(engine.phase, now)

        session.sync_controller()
        if abs(session.thumbstick_y) > 0.1:  # deadzone
            pitch_offset -= session.thumbstick_y * dt * 1.5  # ~85°/sec at full tilt
            pitch_offset = max(-math.pi / 2, min(math.pi / 2, pitch_offset))

        display_phase = display_phase_for_position(engine.phase, state.shape)
        frame_idx = display_index_for_phase(
            phase=display_phase,
            frame_count=frame_count,
            auto_active=state.playing and not rh_paused["value"],
            current_frame_index=last_frame_idx if last_frame_idx >= 0 else None,
        )

        if frame_idx != last_frame_idx:
            renderer.upload_frame(frames[frame_idx])
            last_frame_idx = frame_idx

        if should_render and views:
            pitch_mat = _pitch_rotation_matrix(pitch_offset) if pitch_offset != 0.0 else None

            for eye_index, view in enumerate(views):
                session.bind_eye_framebuffer(eye_index)

                proj = fov_to_projection_matrix(
                    view.fov.angle_left,
                    view.fov.angle_right,
                    view.fov.angle_up,
                    view.fov.angle_down,
                    0.05,
                    100.0,
                )
                view_mat = pose_to_view_matrix(
                    (0.0, 0.0, 0.0),
                    (view.pose.orientation.x, view.pose.orientation.y,
                     view.pose.orientation.z, view.pose.orientation.w),
                )

                vp = proj @ view_mat
                if pitch_mat is not None:
                    vp = vp @ pitch_mat
                inv_vp = np.linalg.inv(vp)
                renderer.render_eye(eye_index, inv_vp)

                session.release_eye_framebuffer(eye_index)

        session.frame_end(display_time, views)
        glfw.poll_events()
