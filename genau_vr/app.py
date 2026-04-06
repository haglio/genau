"""GenauVR — VR180 clip player with OSR2 T-Code sync.

Features: voice commands, cruise control, VR controller pitch adjust.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import threading
import time
from pathlib import Path

import numpy as np

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


def _resolve_clip_path(args: argparse.Namespace, cfg: dict) -> Path:
    if args.clip:
        p = Path(args.clip)
        if not p.exists():
            print(f"Error: clip not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p

    vr_clips_dir = cfg.get("vr_clips_dir")
    if vr_clips_dir:
        vr_dir = Path(vr_clips_dir)
        if vr_dir.exists():
            clips = scan_clips(vr_dir)
            return clips[0]

    clips_dir = cfg.get("clips_dir")
    if clips_dir:
        return scan_clips(Path(clips_dir))[0]

    print("Error: no clip specified and no clips_dir in config", file=sys.stderr)
    sys.exit(1)


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


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args = _parse_args(argv)
    cfg = _load_config(args)
    clip_path = _resolve_clip_path(args, cfg)
    tcode_host, tcode_port = _resolve_tcode_endpoint(cfg)

    logger.info("Loading clip: %s", clip_path)
    frames = load_clip(clip_path)
    logger.info("Loaded %d frames (%dx%d)", len(frames), frames[0].shape[1], frames[0].shape[0])

    from .vr_renderer import VRRenderer
    from .vr_session import VRSession

    logger.info("Initializing VR session...")
    session = VRSession()
    renderer = VRRenderer()

    state = DirectControlState(playing=True, speed=args.speed, shape=WaveformShape.SINE)
    engine = PlaybackEngine(last_tick=time.monotonic())
    cruise = CruiseControlState()
    tcode_sink = UdpTCodeSink(tcode_host, tcode_port)
    tcode_sender = RateLimitedTCodeSender(tcode_sink, direct_state=state)

    # Command file for voice commands
    state_dir = Path(cfg.get("state_dir", "state"))
    if not state_dir.is_absolute():
        state_dir = DEFAULT_CONFIG.parent / state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    cmd_file = state_dir / "genau_vr_cmd.txt"

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
                  frames, cmd_file, stop_event, rh_paused)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        tcode_sender.close()
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
    cmd_file: Path,
    stop_event: threading.Event,
    rh_paused: dict,
) -> None:
    import glfw

    frame_count = len(frames)
    last_frame_idx = -1
    pitch_offset = 0.0
    last_time = time.monotonic()

    def step_clip(delta: int) -> None:
        pass  # Single-clip MVP — no playlist yet

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

        # Process voice commands
        command = _consume_command_file(cmd_file)
        if command:
            apply_runtime_command(
                command,
                engine=engine,
                rh_paused=rh_paused,
                step_clip=step_clip,
                direct_state=state,
                cruise_control_state=cruise,
                stop_event=stop_event,
            )

        # Tick cruise control
        tick_cruise_control(state, cruise, now)

        # Update engine
        update_engine(
            engine,
            now=now,
            auto_active=True,
            raw_bpm=state.bpm,
            sync_pulse_id=0,
            beats_per_loop=1.0,
            bpm_smoothing=0.14,
            sync_strength=0.0,
            paused=not state.playing or rh_paused["value"],
        )

        tcode_sender.maybe_send(engine.phase, now)

        # Controller pitch adjustment
        session.sync_controller()
        if abs(session.thumbstick_y) > 0.1:  # deadzone
            pitch_offset += session.thumbstick_y * dt * 1.5  # ~85°/sec at full tilt
            pitch_offset = max(-math.pi / 2, min(math.pi / 2, pitch_offset))

        # Frame selection
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
