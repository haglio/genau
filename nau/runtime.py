"""Fun Time command channel: command strings -> PlayerSession actions.

Commands arrive one per line in the nau command file (consumed with
``player_core.file_channel.consume_command_file(uppercase=False)`` because
PLAY_FILE carries case-sensitive paths). The keyword is case-insensitive;
the argument, when present, is TAB-separated into video and funscript.
"""
from __future__ import annotations

from pathlib import Path

from .session import MAX_SPEED_RATE, MIN_SPEED_RATE

SEEK_STEP_MS = 10_000
SPEED_STEP = 0.25


def apply_command(
    command: str,
    session,
    *,
    stop_event=None,
    reload_playlist=None,
    toggle_length_mode=None,
    set_length_mode=None,
    play_compilation=None,
    play_full_vid=None,
    play_money_shot=None,
    end_compilation=None,
    set_hybrid=None,
    set_f_mode=None,
    set_active=None,
) -> bool:
    parts = command.strip().split(None, 1)
    if not parts:
        return False
    keyword = parts[0].upper()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if keyword == "NEXT":
        session.step(1)
    elif keyword == "PREV":
        session.step(-1)
    elif keyword == "SEEK_FWD":
        session.seek_by(SEEK_STEP_MS)
    elif keyword == "SEEK_BACK":
        session.seek_by(-SEEK_STEP_MS)
    elif keyword == "SPEED_UP":
        session.adjust_speed(SPEED_STEP)
    elif keyword == "SPEED_DOWN":
        session.adjust_speed(-SPEED_STEP)
    elif keyword == "SET_SPEED":
        return _set_speed(session, arg)
    elif keyword == "SET_VOLUME":
        return _set_volume(session, arg)
    elif keyword == "RECORD_DOWN":
        session.record_down()
    elif keyword == "RECORD_UP":
        session.record_up()
    elif keyword == "RECORD_TAP":
        _record_tap(session)
    elif keyword == "LOOP_CANCEL":
        session.loop_cancel()
    elif keyword == "CYCLE_VERSION":
        session.cycle_version()
    elif keyword == "PLAY_FILE" and arg:
        video_part, _, funscript_part = arg.partition("\t")
        funscript_part = funscript_part.strip()
        session.play_file(
            Path(video_part.strip()),
            Path(funscript_part) if funscript_part else None,
        )
    elif keyword == "RELOAD_PLAYLIST":
        if reload_playlist is not None:
            reload_playlist()
    elif keyword == "TOGGLE_LENGTH_MODE":
        if toggle_length_mode is None:
            return False
        toggle_length_mode()
    elif keyword == "SET_LENGTH_MODE":
        if set_length_mode is None or not arg:
            return False
        set_length_mode(arg)
    elif keyword == "PLAY_COMPILATION":
        if play_compilation is None:
            return False
        play_compilation()
    elif keyword == "PLAY_FULL_VID":
        if play_full_vid is None:
            return False
        play_full_vid()
    elif keyword == "PLAY_MONEY_SHOT":
        if play_money_shot is None:
            return False
        play_money_shot()
    elif keyword == "END_COMPILATION":
        # Out of a compilation without naming a length: back to the mode that was
        # feeding the playlist when it was entered.
        if end_compilation is None:
            return False
        end_compilation()
    elif keyword == "SET_TCODE_ENABLED":
        if not arg:
            return False
        session.set_tcode_enabled(arg != "0")
    elif keyword == "SET_HYBRID":
        # In Hybrid, Genau's window is a transparent layer over Nau's and its own
        # panel holds the top-left corner; Nau moves its corner furniture aside.
        # Only the orchestrator knows which mode the primary slot is in.
        if set_hybrid is None or not arg:
            return False
        set_hybrid(arg != "0")
    elif keyword == "SET_F_MODE":
        # F-mode narrows the playlist Fun Time writes to the scripted videos.
        # Nau receives the result and cannot tell it from any other playlist, so
        # the flag has to be said outright for the HUD to be able to show it.
        if set_f_mode is None or not arg:
            return False
        set_f_mode(arg != "0")
    elif keyword == "SET_ACTIVE":
        # Whether a bare, player-less command lands here rather than on a
        # satellite.  Only the orchestrator tracks which player was addressed
        # last, so this is the whole of what Nau knows about it.
        if set_active is None or not arg:
            return False
        set_active(arg != "0")
    elif keyword == "QUIT":
        if stop_event is None:
            return False
        stop_event.set()
    else:
        return False
    return True


def _set_speed(session, arg: str) -> bool:
    """SET_SPEED <min|max|multiplier> -> absolute playback rate. Returns False on
    a missing or non-numeric argument so the caller reports it unhandled."""
    key = arg.lower()
    if key == "min":
        session.set_speed(MIN_SPEED_RATE)
    elif key == "max":
        session.set_speed(MAX_SPEED_RATE)
    else:
        try:
            session.set_speed(float(arg))
        except ValueError:
            return False
    return True


def _set_volume(session, arg: str) -> bool:
    """SET_VOLUME <0-100> -> absolute playback volume. Returns False on a missing
    or non-numeric argument so the caller reports it unhandled."""
    try:
        session.set_volume(int(arg))
    except ValueError:
        return False
    return True


def _record_tap(session) -> None:
    """One-button record cycle: start marking -> finish loop -> cancel."""
    state = session.loop_state
    if state == "normal":
        session.record_down()
    elif state == "recording":
        session.record_up()
    else:
        session.loop_cancel()
