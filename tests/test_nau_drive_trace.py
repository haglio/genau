"""The trace's model: what the device is about to be asked to do, and by whom."""
from __future__ import annotations

import numpy as np
from player_core.funscript import Funscript

from genau.drive_hud import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
)
from nau.drive_trace import drive_readout

# A twelve-second trace, which is what Genau publishes at one beat per loop.
SPAN_S = 12.0


def _stroke(**over) -> DriveHud:
    """Genau's readout as it publishes it: its own stroke, forward from now."""
    return DriveHud(
        speed=50, amplitude=80, center=50, trace_seconds=SPAN_S,
        waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(TRACE_SAMPLES)),
        **over)


def _script(*, until_ms: int) -> Funscript:
    """A script that strokes hard for *until_ms* and then stops for good.

    Densely sampled while it runs, so ``is_resting_at`` reads it as real action,
    and nothing at all after — which is the shape of a scripted segment ending
    mid-video, the moment the handoff is about.
    """
    return Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                              for t in range(0, until_ms + 1, 200)])


def _read(script, *, at: int, published=None, genau_behind=True,
          osr2_has_script=True) -> DriveHud:
    return drive_readout(
        published if published is not None else _stroke(),
        script=script, position_ms=at, genau_behind=genau_behind,
        osr2_has_script=osr2_has_script)


class TestOneLineTwoDrivers:
    """The span runs forward from the playhead, so a handoff that has not happened
    yet is inside it — which is the only way to see the seam on its way in rather
    than after it is over."""

    def test_a_script_running_the_whole_span_is_all_its_own(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=0)

        assert hud.segments == ()
        assert hud.waveform == script.trace(0, round(SPAN_S * 1000), TRACE_SAMPLES)

    def test_the_end_of_a_scripted_stretch_shows_the_stroke_that_takes_over(self):
        """Green for what is left of the script, blue for the stroke waiting, and
        one line across the join."""
        hud = _read(_script(until_ms=4_000), at=0)

        assert [who for _start, _end, who in hud.runs] == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_GENAU]

    def test_the_runs_touch_so_the_line_never_breaks_at_the_join(self):
        hud = _read(_script(until_ms=4_000), at=0)
        first, second = hud.runs

        assert first[1] == second[0]

    def test_the_stroke_side_is_genau_s_own_samples(self):
        """Not the script's last position held flat: what the device will be doing
        after the handoff is the stroke Genau is parked on, and drawing anything
        else there makes the seam unjudgeable."""
        published = _stroke()
        hud = _read(_script(until_ms=4_000), at=0, published=published)
        _start, _end, _who = hud.runs[1]
        tail = hud.runs[1][0]

        assert hud.waveform[tail + 1:] == published.waveform[tail + 1:]

    def test_a_script_about_to_start_up_shows_the_stroke_handing_over(self):
        """The seam runs both ways, and the trace sees this one coming too: the
        stroke Genau is sending now, then the script taking it off him."""
        script = Funscript(actions=[(t, 0 if (t // 200) % 2 else 100)
                                    for t in range(8_000, 9_001, 200)])

        hud = _read(script, at=0, osr2_has_script=False)

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_GENAU, DRIVEN_BY_FUNSCRIPT]

    def test_in_nau_the_gap_is_nobody_s_and_rests_on_the_floor(self):
        """No Genau behind that screen, and the script's own driver rests the
        device — so the picture is the floor, not a stroke that is not coming."""
        hud = drive_readout(
            None, script=_script(until_ms=4_000), position_ms=0,
            genau_behind=False, osr2_has_script=True)
        gap_start = hud.runs[1][0]

        assert [who for _s, _e, who in hud.runs] == [
            DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NOTHING]
        assert set(hud.waveform[gap_start + 1:]) == {0.0}


class TestStillPicture:
    """He watched the line boil: resampled from the playhead every frame, every
    peak landed somewhere slightly different."""

    def test_the_shape_slides_along_rather_than_being_redrawn(self):
        script = _script(until_ms=120_000)
        step_ms = round(SPAN_S * 1000 / (TRACE_SAMPLES - 1))

        first = _read(script, at=0).waveform
        later = _read(script, at=step_ms).waveform

        assert later[:-1] == first[1:]

    def test_a_playhead_between_two_samples_draws_the_same_picture(self):
        script = _script(until_ms=120_000)

        assert _read(script, at=17).waveform == _read(script, at=0).waveform


class TestPositionMarker:
    def test_a_script_driving_puts_the_marker_where_the_script_is(self):
        script = _script(until_ms=120_000)

        hud = _read(script, at=300)

        assert hud.position == round(script.position_at(300) / 100 * POSITION_MAX)

    def test_genau_driving_leaves_the_marker_where_genau_published_it(self):
        """It is Genau's device then, and Genau knows where it put it."""
        published = _stroke(position=1234)

        hud = _read(_script(until_ms=120_000), at=0, published=published,
                    osr2_has_script=False)

        assert hud.position == 1234


class TestNothingToFoldIn:
    def test_an_unscripted_video_leaves_the_readout_alone(self):
        published = _stroke()

        assert drive_readout(published, script=None, position_ms=0,
                             genau_behind=True, osr2_has_script=False) == published

    def test_one_driver_over_the_whole_span_says_so_by_saying_nothing(self):
        """An unchanging picture has to compare equal to itself, or the panel is
        repainted per frame for a difference only in how it was described."""
        hud = _read(_script(until_ms=120_000), at=0)

        assert hud.segments == ()
