"""Runtime command dispatch — maps command strings to actions.

Copied from Genau's runtime_commands.py.
"""
from __future__ import annotations

import logging

from .playback import (
    adjust_amplitude,
    adjust_center,
    adjust_speed,
    cycle_shape,
    set_amplitude,
    set_center,
    set_speed,
)
from .cruise_control import (
    disable_cruise_control,
    enable_cruise_control,
    toggle_cruise_control,
)


VOLUME_STEP = 0.1


logger = logging.getLogger(__name__)


def apply_runtime_command(command, **collaborators) -> None:
    """Act on one command, or say on the log that we cannot.

    The dispatcher reports an unanswered verb itself rather than returning a
    flag for a caller to check: it is the only thing that knows, and there is
    one of it rather than one per call site. Two kinds land here — a verb no
    branch matches, and a verb whose collaborator this build did not wire —
    and both mean the same thing to whoever sent it, which is that nothing
    happened.
    """
    if not _dispatch(command, **collaborators):
        logger.warning("Unhandled command: %s", str(command).strip())


def _dispatch(
    command,
    *,
    rh_paused,
    step_clip,
    direct_state=None,
    cruise_control_state=None,
    stop_event=None,
    audio_player=None,
) -> bool:
    if not command:
        return False

    normalized = command.strip().upper()
    if normalized == "QUIT":
        if stop_event is None:
            return False
        stop_event.set()
        return True
    elif normalized == "PREV":
        step_clip(-1)
    elif normalized == "NEXT":
        step_clip(1)
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
    elif normalized == "TOGGLE_CRUISE" and cruise_control_state is not None:
        toggle_cruise_control(cruise_control_state)
    elif normalized == "CRUISE_ON" and cruise_control_state is not None:
        enable_cruise_control(cruise_control_state)
    elif normalized == "CRUISE_OFF" and cruise_control_state is not None:
        disable_cruise_control(cruise_control_state)
    elif normalized == "VOLUME_UP" and audio_player is not None:
        audio_player.adjust_volume(VOLUME_STEP)
    elif normalized == "VOLUME_DOWN" and audio_player is not None:
        audio_player.adjust_volume(-VOLUME_STEP)
    else:
        return _try_numeric_command(normalized, direct_state)
    return True


_NUMERIC_SETTERS = {
    "AMP": set_amplitude,
    "CENTER": set_center,
    "SPEED": set_speed,
}


def _try_numeric_command(normalized: str, direct_state) -> bool:
    if direct_state is None:
        return False
    parts = normalized.split(None, 1)
    if len(parts) != 2:
        return False
    keyword, raw_value = parts
    setter = _NUMERIC_SETTERS.get(keyword)
    if setter is None:
        return False
    try:
        value = int(raw_value)
    except ValueError:
        return False
    setter(direct_state, value)
    return True
