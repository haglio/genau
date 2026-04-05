from __future__ import annotations

from .engine import PlaybackEngine
from .direct_control import adjust_speed, adjust_amplitude, adjust_center, cycle_shape
from .auto_pilot import toggle_auto_pilot


QUARTER_CYCLE_OFFSET_COMMAND = "OFFSET_QUARTER_CYCLE"
LEGACY_QUARTER_CYCLE_OFFSET_COMMAND = "NUDGE25"


def apply_runtime_command(
    command,
    *,
    engine: PlaybackEngine,
    rh_paused,
    step_clip,
    direct_state=None,
    auto_pilot_state=None,
) -> bool:
    if not command:
        return False

    normalized = command.strip().upper()
    if normalized == "PREV":
        step_clip(-1)
    elif normalized == "NEXT":
        step_clip(1)
    elif normalized in {QUARTER_CYCLE_OFFSET_COMMAND, LEGACY_QUARTER_CYCLE_OFFSET_COMMAND}:
        engine.phase = (engine.phase + 0.25) % 1.0
    elif normalized == "PAUSE":
        rh_paused["value"] = True
        if direct_state is not None:
            direct_state.playing = False
    elif normalized == "RESUME":
        rh_paused["value"] = False
        if direct_state is not None:
            direct_state.playing = True
    elif normalized == "SPEED_DOWN" and direct_state is not None:
        adjust_speed(direct_state, -5)
    elif normalized == "SPEED_UP" and direct_state is not None:
        adjust_speed(direct_state, 5)
    elif normalized == "AMPLITUDE_DOWN" and direct_state is not None:
        adjust_amplitude(direct_state, -10)
    elif normalized == "AMPLITUDE_UP" and direct_state is not None:
        adjust_amplitude(direct_state, 10)
    elif normalized == "CENTER_DOWN" and direct_state is not None:
        adjust_center(direct_state, -5)
    elif normalized == "CENTER_UP" and direct_state is not None:
        adjust_center(direct_state, 5)
    elif normalized == "CYCLE_SHAPE" and direct_state is not None:
        cycle_shape(direct_state)
    elif normalized == "TOGGLE_AUTO" and auto_pilot_state is not None:
        toggle_auto_pilot(auto_pilot_state)
    else:
        return False
    return True
