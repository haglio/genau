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
    play_clip_jump=None,
    jump_to_funscript=None,
    next_funscripted=None,
    end_compilation=None,
    set_f_mode=None,
    set_volume_hud=None,
    set_display=None,
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
        return _set_volume(session, arg, set_volume_hud)
    elif keyword == "RECORD_DOWN":
        session.record_down()
    elif keyword == "RECORD_UP":
        session.record_up()
    elif keyword == "RECORD_TAP":
        _record_tap(session)
    elif keyword == "LOOP_CANCEL":
        session.loop_cancel()
    elif keyword == "SET_LOOP":
        return _set_loop(session, arg)
    elif keyword == "TOGGLE_LOCK":
        session.toggle_lock()
    elif keyword in ("LOCK_ON", "LOCK_OFF"):
        # Named absolutely as well as toggled, because the spoken forms are
        # "primary lock" and "primary unlock": a speaker asks for the state they
        # want, not for the other one.
        session.set_locked(keyword == "LOCK_ON")
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
    elif keyword == "PLAY_CLIP_JUMP":
        if play_clip_jump is None:
            return False
        play_clip_jump()
    elif keyword == "JUMP_TO_FUNSCRIPT":
        # Past the quiet stretch, to where this video's scripting starts again.
        if jump_to_funscript is None:
            return False
        jump_to_funscript()
    elif keyword == "NEXT_FUNSCRIPTED":
        # Give up on this video for the next scripted one, at its action.
        if next_funscripted is None:
            return False
        next_funscripted()
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
    elif keyword == "SET_F_MODE":
        # F-mode narrows the playlist Fun Time writes to the scripted videos.
        # Nau receives the result and cannot tell it from any other playlist, so
        # the flag has to be said outright for the HUD to be able to show it.
        if set_f_mode is None or not arg:
            return False
        set_f_mode(arg != "0")
    elif keyword in ("DISPLAY_ON", "DISPLAY_OFF"):
        # Whether Nau owns the primary rect right now, which is not the same as
        # whether it is playing: Fun Time hands that rect to Genau in genau mode
        # and minimizes Nau, and a minimized window keeps its taskbar button — so
        # without this an alt-tab back lands on the frame it was paused on.  The
        # mirror of the DISPLAY_ON/DISPLAY_OFF Genau is sent (see nau.display).
        if set_display is None:
            return False
        set_display(keyword == "DISPLAY_ON")
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


def _set_loop(session, arg: str) -> bool:
    """SET_LOOP <in_ms> <out_ms> -> a loop this player was left running.

    The one piece of Nau's state an orchestrator has to hand back rather than
    rebuild: a loop is a range inside one video, so it dies with the process
    while everything else rides in on the playlist or a flag file.  The bounds
    come straight off the status file this player published, already snapped, so
    they are asserted rather than marked.  Returns False on anything it cannot
    read as two numbers, so the caller reports it unhandled.
    """
    in_part, _, out_part = arg.partition(" ")
    try:
        in_ms, out_ms = int(in_part), int(out_part)
    except ValueError:
        return False
    session.restore_loop(in_ms, out_ms)
    return True


def _set_volume(session, arg: str, set_volume_hud=None) -> bool:
    """SET_VOLUME <0-100> [muted] -> the primary display's sound level.

    The mute comes as a flag of its own rather than as a level of zero.  Zero is
    what an audio *sink* needs and all Fun Time used to send, but a control that
    has to be looked at cannot tell silent from turned-all-the-way-down from it —
    and unmuting has to come back to the level the speaker chose.  So the level is
    what is drawn, the mute is drawn over it, and the audible loudness is worked
    out here.  Returns False on a missing or non-numeric level, so the caller
    reports it unhandled.
    """
    level, _, muted_arg = arg.partition(" ")
    try:
        volume = int(level)
    except ValueError:
        return False
    muted = muted_arg.strip() not in ("", "0")
    session.set_volume(0 if muted else volume)
    if set_volume_hud is not None:
        set_volume_hud(volume, muted)
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
