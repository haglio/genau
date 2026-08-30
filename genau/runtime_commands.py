from __future__ import annotations

import logging

from .controls import VERBS, GenauControls
logger = logging.getLogger(__name__)

QUARTER_CYCLE_OFFSET_COMMAND = "OFFSET_QUARTER_CYCLE"


def apply_runtime_command(command, controls: GenauControls) -> None:
    """Act on one command, or say on the log that we cannot.

    The dispatcher reports an unanswered verb itself rather than returning a
    flag for a caller to check: it is the only thing that knows, and there is
    one of it rather than one per call site. Two kinds land here — a verb no
    branch matches, and a verb whose collaborator this build did not wire —
    and both mean the same thing to whoever sent it, which is that nothing
    happened.
    """
    if not _dispatch(command, controls):
        logger.warning("Unhandled command: %s", str(command).strip())


def _dispatch(command, controls: GenauControls) -> bool:
    if not command:
        return False

    normalized = command.strip().upper()

    # A verb its control declared: looked up rather than compared against, so
    # adding one is a record in genau/controls.py and nothing here.
    said = normalized.split(None, 1)
    if said:
        declared = VERBS.get(said[0])
        if declared is not None:
            return _act(declared, controls, said[1] if len(said) > 1 else "")

    engine = controls.engine
    rh_paused = controls.rh_paused
    step_clip = controls.step_clip
    discard_clip = controls.discard_clip
    direct_state = controls.direct_state
    stop_event = controls.stop_event
    hud_state = controls.hud_state
    display_state = controls.display_state
    set_volume = controls.set_volume
    reorder_clips = controls.reorder_clips

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
        return _try_numeric_command(normalized, set_volume)
    return True


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


def _act(declared: tuple, controls: GenauControls, value: str) -> bool:
    """Run a declared verb, or say why it cannot run.

    Three ways it does not: the control this build did not wire, a value on a
    verb that takes none, and none on a verb that wants one.  All three read the
    same to whoever sent it -- nothing happened -- and all three are logged.
    """
    control, verb = declared
    if not control.can_act(controls):
        return False
    if verb.takes_a_value != bool(value):
        return False
    return verb.act(controls, value)


def _try_numeric_command(normalized: str, set_volume=None) -> bool:
    parts = normalized.split(None, 1)
    if len(parts) != 2:
        return False
    keyword, raw_value = parts
    if keyword == "SET_VOLUME":
        return _set_volume_command(raw_value, set_volume)
    return False

