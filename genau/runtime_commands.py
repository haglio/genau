from __future__ import annotations

import logging

from .engine import PlaybackEngine
from player_core.direct_control import (
    adjust_speed,
    adjust_amplitude,
    adjust_center,
    cycle_shape,
    set_amplitude,
    set_center,
    set_speed,
)
from player_core.cruise_control import (
    disable_cruise_control,
    enable_cruise_control,
    toggle_cruise_control,
)
from .clip_advance import (
    adjust_interval,
    set_interval,
    set_locked,
    toggle_lock,
)


logger = logging.getLogger(__name__)

QUARTER_CYCLE_OFFSET_COMMAND = "OFFSET_QUARTER_CYCLE"


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
    engine: PlaybackEngine,
    rh_paused,
    step_clip,
    discard_clip=None,
    direct_state=None,
    cruise_control_state=None,
    set_stroke_phase=None,
    clip_advance_state=None,
    stop_event=None,
    hud_state=None,
    display_state=None,
    set_volume=None,
    reorder_clips=None,
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
    elif normalized == "WEIRD" and discard_clip is not None:
        discard_clip()
    # The two browse orders every player in the room has, said to the one player
    # with no playlist file to hand it: Genau owns its own sequence, so the order
    # is a verb rather than a rewritten list, and answering it rescans the clips
    # folder — which is most of what Latest is for.
    elif normalized in ("LATEST", "SHUFFLE") and reorder_clips is not None:
        reorder_clips(normalized == "LATEST")
    elif normalized == QUARTER_CYCLE_OFFSET_COMMAND:
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
    elif normalized == "CYCLE_SHAPE_PREV" and direct_state is not None:
        cycle_shape(direct_state, -1)
    elif normalized == "TOGGLE_CRUISE" and cruise_control_state is not None:
        _handed_back(toggle_cruise_control(cruise_control_state),
                     set_stroke_phase)
    elif normalized == "CRUISE_ON" and cruise_control_state is not None:
        enable_cruise_control(cruise_control_state)
    elif normalized == "CRUISE_OFF" and cruise_control_state is not None:
        _handed_back(disable_cruise_control(cruise_control_state),
                     set_stroke_phase)
    # The lock, under the same three verbs Nau answers to, because it is the same
    # thing on both: hold what is on screen, or let it move on.  Whichever player
    # owns the main slot gets them, and the one padlock on the console is what
    # sends them.
    elif normalized == "TOGGLE_LOCK" and clip_advance_state is not None:
        toggle_lock(clip_advance_state)
    elif normalized in ("LOCK_ON", "LOCK_OFF") and clip_advance_state is not None:
        set_locked(clip_advance_state, normalized == "LOCK_ON")
    # How long a clip holds the screen, a second at a time.  Named for the number
    # rather than for the auto-advance that spends it, so the verb reads as what
    # the orchestrator's reference shows and what its speaker says aloud.
    elif normalized == "CLIP_SECONDS_DOWN" and clip_advance_state is not None:
        adjust_interval(clip_advance_state, -1)
    elif normalized == "CLIP_SECONDS_UP" and clip_advance_state is not None:
        adjust_interval(clip_advance_state, 1)
    elif normalized == "HUD_ON" and hud_state is not None:
        hud_state["active"] = True
    elif normalized == "HUD_OFF" and hud_state is not None:
        hud_state["active"] = False
    # Whether Genau owns the screen right now, which is not the same as whether
    # the hand is stroking: an orchestrator switching to a mode Genau doesn't
    # display sends DISPLAY_OFF, and Genau goes dark without touching playback.
    elif normalized == "DISPLAY_ON" and display_state is not None:
        display_state["active"] = True
    elif normalized == "DISPLAY_OFF" and display_state is not None:
        display_state["active"] = False
    else:
        return _try_numeric_command(
            normalized, direct_state, clip_advance_state, set_volume)
    return True


_NUMERIC_SETTERS = {
    "AMP": set_amplitude,
    "CENTER": set_center,
    "SPEED": set_speed,
}


def _set_volume_command(raw: str, set_volume) -> bool:
    """``SET_VOLUME <level> [muted]`` — the sound level Fun Time is publishing.

    Genau neither owns the level (the orchestrator does, for the whole primary
    display) nor plays the audio: a companion process carries the clip music.
    What arrives here is only what the chip Genau draws should show, which is why
    the mute rides alongside the level — a level of zero cannot say whether the
    speaker is off or turned all the way down, nor what unmuting returns to.

    The mute is optional so an orchestrator that sends the level alone still
    moves the slider rather than being ignored outright.
    """
    if set_volume is None:
        return False
    parts = raw.split()
    try:
        level = int(parts[0])
        muted = bool(int(parts[1])) if len(parts) > 1 else False
    except (IndexError, ValueError):
        return False
    set_volume(level, muted)
    return True


def _try_numeric_command(
    normalized: str, direct_state, clip_advance_state, set_volume=None
) -> bool:
    parts = normalized.split(None, 1)
    if len(parts) != 2:
        return False
    keyword, raw_value = parts
    if keyword == "SET_VOLUME":
        return _set_volume_command(raw_value, set_volume)
    try:
        value = int(raw_value)
    except ValueError:
        return False

    # "clip seconds thirty" names the seconds a clip holds the screen.  It says
    # nothing about the lock: a held clip stays held, and this is the pace it
    # will move at once it is let go.
    if keyword == "CLIP_SECONDS":
        if clip_advance_state is None:
            return False
        set_interval(clip_advance_state, value)
        return True

    setter = _NUMERIC_SETTERS.get(keyword)
    if setter is None or direct_state is None:
        return False
    setter(direct_state, value)
    return True


def _handed_back(phase, set_stroke_phase) -> None:
    """Cruise control letting go says where the single wave should pick up — at
    the phase of the wave that had most of the travel, which is the one the
    device was mostly following. Nowhere to put it (a caller with no sender) and
    the stroke simply resumes on its own free-running phase."""
    if phase is not None and set_stroke_phase is not None:
        set_stroke_phase(phase)
