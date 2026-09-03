"""GenauVR's frame loop.

One turn: read what the headset and the command file have to say, move the
stroke and the picture on, then draw both eyes.  It was one function of a
hundred and thirty-four lines taking twelve collaborators, holding five
loop-carried locals and rebinding four of them through a nested closure -- the
single hardest thing in the unit to change, and where the frame budget lives.

What is left here is the sequence.  The clips are a ClipCarousel, the tilt a
PitchControl, the verbs a GenauVrControls, and the per-eye body is
:func:`render_views`.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from .carousel import ClipCarousel
from .controls import GenauVrControls
from .cruise_control import CruiseControlState, tick_cruise_control
from .pitch import PitchControl
from .playback import (
    DirectControlState,
    PlaybackEngine,
    RateLimitedTCodeSender,
    display_phase_for_position,
    update_engine,
)
from .projection import fov_to_projection_matrix, pose_to_view_matrix
from .runtime_commands import apply_runtime_command

logger = logging.getLogger(__name__)

# How close and how far the projection reaches, in metres.  The picture is a
# sphere a little way out, so the near plane only has to clear the viewer's own
# head and the far plane only has to contain the sphere.
NEAR_PLANE_M = 0.05
FAR_PLANE_M = 100.0

# GenauVR's own beat, deliberately not the numbers genau_config.json carries for
# Genau: one beat to a loop, because a VR clip loops on its own length rather
# than on a bar of the room's music, and a gentler smoothing because there is no
# broker sending a BPM for it to chase.
BEATS_PER_LOOP = 1.0
BPM_SMOOTHING = 0.14

# How long to wait between polls while the runtime has not begun the session.
_NOT_READY_SLEEP_S = 0.01


def render_views(session, renderer, views, pitch_mat) -> None:
    """Draw one frame into each eye's framebuffer.

    Each eye has its own projection (the headset's lenses are not symmetric) and
    its own pose, and the shader is handed the *inverse* of the two multiplied
    together -- it walks a ray per pixel back out into the sphere rather than
    projecting the sphere forwards.
    """
    for eye_index, view in enumerate(views):
        session.bind_eye_framebuffer(eye_index)

        proj = fov_to_projection_matrix(
            view.fov.angle_left,
            view.fov.angle_right,
            view.fov.angle_up,
            view.fov.angle_down,
            NEAR_PLANE_M,
            FAR_PLANE_M,
        )
        view_mat = pose_to_view_matrix(
            (0.0, 0.0, 0.0),
            (view.pose.orientation.x, view.pose.orientation.y,
             view.pose.orientation.z, view.pose.orientation.w),
        )

        vp = proj @ view_mat
        if pitch_mat is not None:
            vp = vp @ pitch_mat
        renderer.render_eye(eye_index, np.linalg.inv(vp))

        session.release_eye_framebuffer(eye_index)


def controls_for(
    carousel: ClipCarousel,
    engine: PlaybackEngine,
    state: DirectControlState,
    cruise: CruiseControlState,
    audio,
    stop_event: threading.Event,
) -> GenauVrControls:
    """Everything a command may move, built once where the parts are.

    Stepping the clip goes through the carousel and resets the phase, so a new
    clip starts at its own top rather than part-way through -- it has its own
    length, and carrying the old phase across would open it somewhere arbitrary.
    """
    def step_clip(delta: int) -> None:
        if carousel.step(delta):
            engine.phase = 0.0

    return GenauVrControls(
        step_clip=step_clip,
        direct_state=state,
        cruise_control_state=cruise,
        stop_event=stop_event,
        audio_player=audio,
    )


def run_loop(
    session,
    renderer,
    engine: PlaybackEngine,
    controls: GenauVrControls,
    carousel: ClipCarousel,
    tcode_sender: RateLimitedTCodeSender,
    cmd_file: Path,
    consume_command,
) -> None:
    import glfw

    state = controls.direct_state
    cruise = controls.cruise_control_state
    stop_event = controls.stop_event
    pitch = PitchControl()
    last_time = time.monotonic()

    while session.running and not stop_event.is_set():
        session.poll_events()
        if not session.running or session.window_close_requested:
            break

        if not session.session_ready:
            glfw.poll_events()
            time.sleep(_NOT_READY_SLEEP_S)
            continue

        should_render, display_time, views = session.frame_begin()

        now = time.monotonic()
        dt = now - last_time
        last_time = now

        command = consume_command(cmd_file)
        if command:
            apply_runtime_command(command, controls)

        tick_cruise_control(state, cruise, now)

        playing = state.playing
        update_engine(
            engine,
            now=now,
            auto_active=True,
            raw_bpm=state.bpm,
            beats_per_loop=BEATS_PER_LOOP,
            bpm_smoothing=BPM_SMOOTHING,
            paused=not playing,
        )

        tcode_sender.maybe_send(engine.phase, now)

        session.sync_controller()
        pitch.follow(session.thumbstick_y, dt)

        frame = carousel.frame_for_phase(
            display_phase_for_position(engine.phase, state.shape),
            auto_active=playing,
        )
        if frame is not None:
            renderer.upload_frame(frame)

        if should_render and views:
            render_views(session, renderer, views, pitch.matrix())

        session.frame_end(display_time, views)
        glfw.poll_events()
