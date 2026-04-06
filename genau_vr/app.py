"""GenauVR — VR180 clip player with OSR2 T-Code sync."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

from .clip import load_clip, scan_clips
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

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "genau_config.json"
DEFAULT_TCODE_HOST = "127.0.0.1"
DEFAULT_TCODE_PORT = 50557


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GenauVR — VR180 clip player")
    parser.add_argument("clip", nargs="?", help="Path to a video clip (or uses first clip from config)")
    parser.add_argument("--speed", type=int, default=50, help="Playback speed 0-100 (default: 50)")
    parser.add_argument("--tcode-host", default=None, help="T-Code UDP host")
    parser.add_argument("--tcode-port", type=int, default=None, help="T-Code UDP port")
    parser.add_argument("--config", default=None, help="Path to genau_config.json")
    return parser.parse_args(argv)


def _resolve_clip_path(args: argparse.Namespace) -> Path:
    if args.clip:
        p = Path(args.clip)
        if not p.exists():
            print(f"Error: clip not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    if not config_path.exists():
        print(f"Error: no clip specified and config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with config_path.open() as f:
        cfg = json.load(f)
    clips_dir = Path(cfg["clips_dir"])
    clips = scan_clips(clips_dir)
    return clips[0]


def _resolve_tcode_endpoint(args: argparse.Namespace) -> tuple[str, int]:
    host = args.tcode_host or DEFAULT_TCODE_HOST
    port = args.tcode_port or DEFAULT_TCODE_PORT

    if args.config and (args.tcode_host is None or args.tcode_port is None):
        config_path = Path(args.config)
        if config_path.exists():
            with config_path.open() as f:
                cfg = json.load(f)
            genau = cfg.get("genau", {})
            if args.tcode_host is None:
                host = genau.get("tcode_udp_host", host)
            if args.tcode_port is None:
                port = genau.get("tcode_udp_port", port)

    return host, port


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args = _parse_args(argv)
    clip_path = _resolve_clip_path(args)
    tcode_host, tcode_port = _resolve_tcode_endpoint(args)

    logger.info("Loading clip: %s", clip_path)
    frames = load_clip(clip_path)
    logger.info("Loaded %d frames (%dx%d)", len(frames), frames[0].shape[1], frames[0].shape[0])

    # Late import so tests that import app.py don't need OpenXR/GL
    from .vr_renderer import VRRenderer
    from .vr_session import VRSession

    logger.info("Initializing VR session...")
    session = VRSession()
    renderer = VRRenderer()

    state = DirectControlState(playing=True, speed=args.speed, shape=WaveformShape.SINE)
    engine = PlaybackEngine(last_tick=time.monotonic())
    tcode_sink = UdpTCodeSink(tcode_host, tcode_port)
    tcode_sender = RateLimitedTCodeSender(tcode_sink, direct_state=state)

    logger.info("Entering VR loop (speed=%d, BPM=%.1f, tcode=%s:%d)", state.speed, state.bpm, tcode_host, tcode_port)

    try:
        _run_loop(session, renderer, engine, state, tcode_sender, frames)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        tcode_sender.close()
        renderer.close()
        session.close()
        logger.info("Shutdown complete")


def _run_loop(
    session,
    renderer,
    engine: PlaybackEngine,
    state: DirectControlState,
    tcode_sender: RateLimitedTCodeSender,
    frames: list[np.ndarray],
) -> None:
    import glfw

    frame_count = len(frames)
    last_frame_idx = -1
    loop_count = 0

    while session.running:
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
        loop_count += 1
        if loop_count <= 5:
            logger.info(
                "Frame %d: should_render=%s, views=%d, state=%s",
                loop_count, should_render, len(views), session._session_state.name,
            )

        now = time.monotonic()
        update_engine(
            engine,
            now=now,
            auto_active=True,
            raw_bpm=state.bpm,
            sync_pulse_id=0,
            beats_per_loop=1.0,
            bpm_smoothing=0.14,
            sync_strength=0.0,
            paused=not state.playing,
        )

        tcode_sender.maybe_send(engine.phase, now)

        display_phase = display_phase_for_position(engine.phase, state.shape)
        frame_idx = display_index_for_phase(
            phase=display_phase,
            frame_count=frame_count,
            auto_active=state.playing,
            current_frame_index=last_frame_idx if last_frame_idx >= 0 else None,
        )

        if frame_idx != last_frame_idx:
            renderer.upload_frame(frames[frame_idx])
            last_frame_idx = frame_idx

        if should_render and views:
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
                    (view.pose.position.x, view.pose.position.y, view.pose.position.z),
                    (view.pose.orientation.x, view.pose.orientation.y,
                     view.pose.orientation.z, view.pose.orientation.w),
                )

                vp = proj @ view_mat
                inv_vp = np.linalg.inv(vp)
                renderer.render_eye(eye_index, inv_vp)

                session.release_eye_framebuffer(eye_index)

        session.frame_end(display_time, views)
        glfw.poll_events()
