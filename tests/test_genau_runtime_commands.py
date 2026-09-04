"""Tests for genau.runtime_commands."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

import pytest
from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState, WaveformShape

from genau.clip_advance import MAX_INTERVAL_S, MIN_INTERVAL_S, ClipAdvanceState
from genau.controls import QUARTER_CYCLE_OFFSET_COMMAND, GenauControls
from genau.engine import PlaybackEngine
from genau.flags import Flag
from genau.runtime_commands import apply_runtime_command


@contextmanager
def _nothing_logged():
    """Collect the dispatcher's warnings for the duration of one call."""
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("genau.runtime_commands")
    handler = _Collect()
    logger.addHandler(handler)
    previous, logger.propagate = logger.propagate, False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def _answered(command, **collaborators) -> bool:
    """Run one verb; True when the dispatcher answered it.

    The dispatcher returns nothing — an unanswered verb goes on the log, which
    is the only place production can see it — so every case below asks the log
    the same question it used to ask the return value.
    """
    with _nothing_logged() as unanswered:
        apply_runtime_command(command, GenauControls(**collaborators))
    return not unanswered



class TestApplyRuntimeCommand:
    def test_prev_steps_backward(self):
        steps: list[int] = []
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            "PREV",
            engine=engine,
            paused=paused,
            step_clip=steps.append,
        )

        assert handled is True
        assert steps == [-1]

    def test_next_steps_forward(self):
        steps: list[int] = []
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            "NEXT",
            engine=engine,
            paused=paused,
            step_clip=steps.append,
        )

        assert handled is True
        assert steps == [1]

    def test_offset_quarter_cycle_advances_phase(self):
        engine = PlaybackEngine(phase=0.1, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            QUARTER_CYCLE_OFFSET_COMMAND,
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert engine.phase == pytest.approx(0.35)

    def test_offset_quarter_cycle_wraps_phase(self):
        engine = PlaybackEngine(phase=0.9, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            QUARTER_CYCLE_OFFSET_COMMAND,
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert engine.phase == pytest.approx(0.15)

    @pytest.mark.parametrize("verb", ["NUDGE25", "SLOW_DOWN"])
    def test_a_spelling_nothing_sends_is_not_a_verb(self, verb):
        """Two aliases had no sender in any of the eleven repos.

        The live spellings are OFFSET_QUARTER_CYCLE, which Fun Time posts, and
        SPEED_DOWN, which Genau's own voice grammar maps "slow down" to. These
        two are now reported unhandled like any other unknown line.
        """
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        ds = DirectControlState(playing=True, speed=50)

        handled = _answered(
            verb,
            engine=engine,
            paused=Flag(),
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is False
        assert engine.phase == pytest.approx(0.0)
        assert ds.speed == 50

    def test_pause_sets_paused(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            "PAUSE",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert paused.on is True

    def test_resume_clears_paused(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag(on=True)

        handled = _answered(
            "RESUME",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is True
        assert paused.on is False

    def test_pause_sets_direct_state_not_playing(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True)

        apply_runtime_command("PAUSE", GenauControls(
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        ))

        assert ds.playing is False

    def test_resume_sets_direct_state_playing(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag(on=True)
        ds = DirectControlState(playing=False)

        apply_runtime_command("RESUME", GenauControls(
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        ))

        assert ds.playing is True

    def test_speed_down_decreases_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, speed=50)

        handled = _answered(
            "SPEED_DOWN",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 45

    def test_speed_up_increases_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, speed=50)

        handled = _answered(
            "SPEED_UP",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 55

    def test_amplitude_down_decreases_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, amplitude=80)

        handled = _answered(
            "AMPLITUDE_DOWN",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 70

    def test_amplitude_up_increases_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, amplitude=80)

        handled = _answered(
            "AMPLITUDE_UP",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 90

    def test_center_down_decreases_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = _answered(
            "CENTER_DOWN",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 45

    def test_center_up_increases_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = _answered(
            "CENTER_UP",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 55

    def test_cycle_shape_advances_shape(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True)
        assert ds.shape == WaveformShape.SINE

        handled = _answered(
            "CYCLE_SHAPE",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.shape == WaveformShape.TRIANGLE

    def test_cycle_shape_prev_reverses_shape(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True)
        assert ds.shape == WaveformShape.SINE

        handled = _answered(
            "CYCLE_SHAPE_PREV",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.shape == WaveformShape.SAWTOOTH  # SINE wraps backward to SAWTOOTH

    def test_toggle_cruise_activates_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        auto = CruiseControlState(active=False)

        handled = _answered(
            "TOGGLE_CRUISE",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            cruise_control_state=auto,
        )

        assert handled is True
        assert auto.active is True

    def test_direct_commands_ignored_without_direct_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        for cmd in ("SPEED_DOWN", "SPEED_UP", "AMPLITUDE_DOWN", "AMPLITUDE_UP",
                     "CENTER_DOWN", "CENTER_UP", "CYCLE_SHAPE"):
            handled = _answered(
                cmd,
                engine=engine,
                paused=paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without direct_state"

    def test_toggle_cruise_ignored_without_cruise_control_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            "TOGGLE_CRUISE",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is False

    def test_cruise_on_enables_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        cc = CruiseControlState(active=False)

        handled = _answered(
            "CRUISE_ON",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            cruise_control_state=cc,
        )

        assert handled is True
        assert cc.active is True

    def test_cruise_off_disables_cruise_control(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        cc = CruiseControlState(active=True)

        handled = _answered(
            "CRUISE_OFF",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            cruise_control_state=cc,
        )

        assert handled is True
        assert cc.active is False

    def test_cruise_on_off_ignored_without_cruise_control_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        for cmd in ("CRUISE_ON", "CRUISE_OFF"):
            handled = _answered(
                cmd,
                engine=engine,
                paused=paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without cruise_control_state"

    def test_amp_sets_amplitude(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, amplitude=80)

        handled = _answered(
            "AMP 50",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.amplitude == 50

    def test_center_sets_center(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, intended_center=50, amplitude=40)

        handled = _answered(
            "CENTER 80",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.intended_center == 80

    def test_speed_sets_speed(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True, speed=50)

        handled = _answered(
            "SPEED 30",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is True
        assert ds.speed == 30

    def test_numeric_commands_ignored_without_direct_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        for cmd in ("AMP 50", "CENTER 80", "SPEED 30"):
            handled = _answered(
                cmd,
                engine=engine,
                paused=paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without direct_state"

    def test_numeric_command_with_non_integer_is_ignored(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        ds = DirectControlState(playing=True)

        handled = _answered(
            "AMP abc",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=ds,
        )

        assert handled is False

    def test_quit_sets_stop_event(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        stop = threading.Event()

        handled = _answered(
            "QUIT",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            stop_event=stop,
        )

        assert handled is True
        assert stop.is_set()

    def test_quit_ignored_without_stop_event(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        handled = _answered(
            "QUIT",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
        )

        assert handled is False

    def test_unknown_command_is_ignored(self):
        engine = PlaybackEngine(phase=0.4, last_tick=0.0)
        paused = Flag()
        steps: list[int] = []

        handled = _answered(
            "UNKNOWN",
            engine=engine,
            paused=paused,
            step_clip=steps.append,
        )

        assert handled is False
        assert engine.phase == 0.4
        assert paused.on is False
        assert steps == []

    def test_hud_on_raises_the_hud(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        hud = Flag()

        handled = _answered(
            "HUD_ON",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            hud=hud,
        )

        assert handled is True
        assert hud.on is True

    def test_hud_off_lowers_the_hud(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        hud = Flag(on=True)

        handled = _answered(
            "HUD_OFF",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            hud=hud,
        )

        assert handled is True
        assert hud.on is False

    def test_hud_commands_ignored_without_a_hud_flag(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        for cmd in ("HUD_ON", "HUD_OFF"):
            handled = _answered(
                cmd,
                engine=engine,
                paused=paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without a hud flag"

    def test_display_off_marks_genau_not_the_active_display(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        display = Flag(on=True)

        handled = _answered(
            "DISPLAY_OFF",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            display=display,
        )

        assert handled is True
        assert display.on is False

    def test_display_on_marks_genau_the_active_display(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()
        display = Flag()

        handled = _answered(
            "DISPLAY_ON",
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            display=display,
        )

        assert handled is True
        assert display.on is True

    def test_display_commands_do_not_touch_playback(self):
        """DISPLAY_* is about what's painted, not whether the hand strokes:
        a paused hand stays paused and a running one keeps running."""
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag(on=True)
        direct = DirectControlState(playing=False)
        display = Flag(on=True)

        apply_runtime_command("DISPLAY_OFF", GenauControls(
            engine=engine,
            paused=paused,
            step_clip=lambda _step: None,
            direct_state=direct,
            display=display,
        ))

        assert paused.on is True
        assert direct.playing is False

    def test_display_commands_ignored_without_a_display_flag(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        paused = Flag()

        for cmd in ("DISPLAY_ON", "DISPLAY_OFF"):
            handled = _answered(
                cmd,
                engine=engine,
                paused=paused,
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without a display flag"


class TestClipAdvanceCommands:
    def _apply(self, command, aa):
        return _answered(
            command,
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            clip_advance_state=aa,
        )

    def _apply_volume(self, command, on_volume):
        return _answered(
            command,
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            set_volume=lambda level, muted: on_volume((level, muted)),
        )

    def test_toggle_flips_the_lock(self):
        aa = ClipAdvanceState(locked=True)
        assert self._apply("TOGGLE_LOCK", aa) is True
        assert aa.locked is False

    def test_on_and_off_are_absolute(self):
        aa = ClipAdvanceState(locked=True)
        assert self._apply("LOCK_OFF", aa) is True
        assert aa.locked is False
        assert self._apply("LOCK_ON", aa) is True
        assert aa.locked is True

    def test_a_number_names_the_seconds_and_leaves_the_lock_alone(self):
        """Naming a pace used to arm the moving as well, which made it both a
        setting and a switch.  The padlock is the only switch."""
        aa = ClipAdvanceState(locked=True)
        assert self._apply("CLIP_SECONDS 30", aa) is True
        assert aa.interval == 30
        assert aa.locked is True

    def test_a_named_pace_is_clamped_to_the_usable_range(self):
        aa = ClipAdvanceState()
        self._apply("CLIP_SECONDS 0", aa)
        assert aa.interval == MIN_INTERVAL_S
        self._apply("CLIP_SECONDS 900", aa)
        assert aa.interval == MAX_INTERVAL_S

    def test_the_arrows_step_the_pace_a_second_at_a_time(self):
        aa = ClipAdvanceState(interval=10)
        assert self._apply("CLIP_SECONDS_UP", aa) is True
        assert aa.interval == 11
        assert self._apply("CLIP_SECONDS_DOWN", aa) is True
        assert aa.interval == 10

    def test_the_published_sound_level_reaches_the_chip(self):
        """Genau draws the primary display's volume but owns neither the level
        nor the audio, so Fun Time tells it what to show.  The mute comes with
        the level: a zero cannot say whether the speaker is off or turned all the
        way down, nor what unmuting would return to."""
        shown = []
        assert self._apply_volume("SET_VOLUME 40 1", shown.append) is True
        assert shown == [(40, True)]
        assert self._apply_volume("SET_VOLUME 70 0", shown.append) is True
        assert shown[-1] == (70, False)

    def test_a_level_with_no_mute_still_moves_the_slider(self):
        """An orchestrator that sends the level alone is answered rather than
        ignored — the chip has a level to show either way."""
        shown = []
        assert self._apply_volume("SET_VOLUME 55", shown.append) is True
        assert shown == [(55, False)]

    def test_an_unreadable_level_is_ignored_rather_than_drawn(self):
        shown = []
        for bad in ("SET_VOLUME", "SET_VOLUME loud", "SET_VOLUME 40 up"):
            assert self._apply_volume(bad, shown.append) is False
        assert shown == []

    def test_the_retired_advance_verbs_are_not_answered_to(self):
        """The interval is named for the number now, not for the auto-advance
        that spends it.  The old spelling is gone rather than kept alongside:
        two verbs for one setting is how the two drift into meaning different
        things."""
        aa = ClipAdvanceState(interval=10)
        for cmd in ("ADVANCE_UP", "ADVANCE_DOWN", "ADVANCE 30"):
            assert self._apply(cmd, aa) is False, f"{cmd} should no longer be answered"
        assert aa.interval == 10

    def test_ignored_without_clip_advance_state(self):
        engine = PlaybackEngine(phase=0.0, last_tick=0.0)
        for cmd in (
            "TOGGLE_LOCK", "LOCK_ON", "LOCK_OFF",
            "CLIP_SECONDS_UP", "CLIP_SECONDS_DOWN", "CLIP_SECONDS 30",
        ):
            handled = _answered(
                cmd,
                engine=engine,
                paused=Flag(),
                step_clip=lambda _step: None,
            )
            assert handled is False, f"{cmd} should be ignored without clip_advance_state"


class TestWeirdCommand:
    def test_weird_condemns_the_clip_on_screen(self):
        calls: list[int] = []

        handled = _answered(
            "WEIRD",
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            condemn_clip=lambda: calls.append(1),
        )

        assert handled is True
        assert calls == [1]

    def test_weird_ignored_without_a_way_to_condemn(self):
        handled = _answered(
            "WEIRD",
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
        )

        assert handled is False


class TestBrowseOrderCommands:
    """The two orders every player in the room browses in.  Genau owns its own
    sequence rather than being handed a playlist file, so the order arrives as a
    verb and the answer is a rescan of the clips folder."""

    def test_latest_asks_for_newest_first(self):
        asked: list[bool] = []

        handled = _answered(
            "LATEST",
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            reorder_clips=asked.append,
        )

        assert handled is True
        assert asked == [True]

    def test_shuffle_asks_for_a_reshuffle(self):
        asked: list[bool] = []

        handled = _answered(
            "SHUFFLE",
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            step_clip=lambda _step: None,
            reorder_clips=asked.append,
        )

        assert handled is True
        assert asked == [False]

    def test_ignored_without_a_way_to_reorder(self):
        for cmd in ("LATEST", "SHUFFLE"):
            handled = _answered(
                cmd,
                engine=PlaybackEngine(phase=0.0, last_tick=0.0),
                paused=Flag(),
                step_clip=lambda _step: None,
            )

            assert handled is False, f"{cmd} should be ignored without reorder_clips"


class TestAnUnhandledCommand:
    """The dispatcher says so itself, because it is the only thing that knows.

    Genau's channel takes what Fun Time posts and what its own voice grammar
    hears; a verb from a build that has moved on, or one whose collaborator
    this app did not wire, used to be dropped without a word.
    """

    def _run(self, command, caplog, **collaborators):
        with caplog.at_level("WARNING", logger="genau.runtime_commands"):
            apply_runtime_command(command, GenauControls(
                engine=PlaybackEngine(phase=0.0, last_tick=0.0),
                paused=Flag(),
                step_clip=lambda _step: None,
                **collaborators,
            ))

    def test_an_unknown_verb_is_named_on_the_log(self, caplog):
        self._run("CYCLE_PROJECTION", caplog)

        assert "CYCLE_PROJECTION" in caplog.text

    def test_a_verb_this_build_did_not_wire_is_named_too(self, caplog):
        """SPEED_UP with no stroke state: as unanswerable as a typo."""
        self._run("SPEED_UP", caplog)

        assert "SPEED_UP" in caplog.text

    def test_a_verb_it_acts_on_says_nothing(self, caplog):
        self._run("NEXT", caplog)

        assert caplog.records == []
