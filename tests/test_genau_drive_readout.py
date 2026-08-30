"""The two cadences, and what is asked for at which of them.

Nothing had ever pinned either.  The readout goes out 25 times a second because
its trace scrolls; the console around it is re-read five times a second because
mode, OSR2 and broker move a few times a minute.  Drop either throttle and the
app still works, faster and noisier -- a file written at the refresh rate and a
file read at it -- which is why neither shows up as a failure anywhere else.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genau.clip_advance import ClipAdvanceState
from genau.controls import GenauControls
from genau.drive_readout import DriveReadout
from genau.engine import PlaybackEngine
from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState


class FakeSender:
    let_go_position = None
    stroke_phase = 0.0

    def current_position(self) -> int:
        return 5000


def _controls(**over) -> GenauControls:
    return GenauControls(
        engine=PlaybackEngine(phase=0.0, last_tick=0.0),
        rh_paused={"value": False},
        step_clip=lambda _step: None,
        direct_state=over.get("direct") or DirectControlState(speed=50, amplitude=60),
        cruise_control_state=over.get("cruise") or CruiseControlState(),
        clip_advance_state=ClipAdvanceState(interval=20),
    )


def _publish(path: Path, mode: str) -> None:
    """Write the console file the way Fun Time writes it."""
    path.write_text(json.dumps({"mode": mode}), encoding="utf-8")


def _readout(**over) -> DriveReadout:
    return DriveReadout(
        controls=over.pop("controls", None) or _controls(),
        beats_per_loop=over.pop("beats_per_loop", 4.0),
        tcode_sender=over.pop("tcode_sender", FakeSender()),
        **over,
    )


# Deltas either side of a threshold, chosen as exact binary fractions so the
# comparison is decided by the rule and not by float error -- and chosen close,
# so the threshold cannot be moved a step either way without reddening one of
# them.
JUST_UNDER_DRIVE = 0.0390625     # 5/128, under 0.04
JUST_OVER_DRIVE = 0.04296875     # 11/256, over 0.04
JUST_UNDER_CONSOLE = 0.1953125   # 25/128, under 0.2
JUST_OVER_CONSOLE = 0.203125     # 13/64, over 0.2


class TestHowOftenTheReadoutGoesOut:
    def _published(self, tmp_path):
        drive = tmp_path / "genau_drive.txt"
        return drive, _readout(drive_file=drive)

    def test_the_first_tick_publishes(self, tmp_path):
        drive, readout = self._published(tmp_path)

        readout.update(1.0)

        assert drive.exists()

    def test_a_tick_too_soon_after_it_does_not(self, tmp_path):
        drive, readout = self._published(tmp_path)
        readout.update(1.0)
        drive.write_text("stale", encoding="utf-8")

        readout.update(1.0 + JUST_UNDER_DRIVE)

        assert drive.read_text(encoding="utf-8") == "stale"

    def test_a_tick_far_enough_after_it_does(self, tmp_path):
        drive, readout = self._published(tmp_path)
        readout.update(1.0)
        drive.write_text("stale", encoding="utf-8")

        readout.update(1.0 + JUST_OVER_DRIVE)

        assert drive.read_text(encoding="utf-8") != "stale"

    def test_a_build_with_nowhere_to_publish_says_nothing(self):
        _readout().update(1.0)   # must not raise


class TestHowOftenTheConsoleIsReRead:
    def test_the_first_tick_reads_it(self, tmp_path):
        console = tmp_path / "console.txt"
        _publish(console, "nau")
        shown = []
        readout = _readout(console_file=console, set_console=shown.append)

        readout.update(1.0)

        assert shown[-1].console.mode == "nau"

    def test_a_tick_too_soon_after_it_keeps_the_model_it_had(self, tmp_path):
        console = tmp_path / "console.txt"
        _publish(console, "nau")
        shown = []
        readout = _readout(console_file=console, set_console=shown.append)
        readout.update(1.0)

        _publish(console, "hybrid")
        readout.update(1.0 + JUST_UNDER_CONSOLE)

        assert shown[-1].console.mode == "nau"

    def test_a_tick_far_enough_after_it_takes_the_new_one(self, tmp_path):
        console = tmp_path / "console.txt"
        _publish(console, "nau")
        shown = []
        readout = _readout(console_file=console, set_console=shown.append)
        readout.update(1.0)

        _publish(console, "hybrid")
        readout.update(1.0 + JUST_OVER_CONSOLE)

        assert shown[-1].console.mode == "hybrid"

    def test_a_standalone_genau_names_itself(self, tmp_path):
        """No file behind it, and the panel still draws sensibly."""
        shown = []

        _readout(set_console=shown.append).update(1.0)

        assert shown[-1].console.mode == "genau"

    def test_a_half_written_file_keeps_the_last_one_rather_than_blanking(self, tmp_path):
        """Fun Time replaces this file while Genau polls it, so a lost race must
        not empty the panel for a frame."""
        console = tmp_path / "console.txt"
        _publish(console, "hybrid")
        shown = []
        readout = _readout(console_file=console, set_console=shown.append)
        readout.update(1.0)

        console.write_text("{\"mo", encoding="utf-8")   # caught mid-replace
        readout.update(1.0 + JUST_OVER_CONSOLE)

        assert shown[-1].console.mode == "hybrid"


class TestWhatThePanelIsToldEachTime:
    def test_the_clip_is_asked_for_as_the_panel_is_built(self, tmp_path):
        """Captured when the readout was built, the panel would name the clip
        the session opened on for the rest of the session."""
        on_screen = [Path("first clip.mp4")]
        shown = []
        readout = _readout(set_console=shown.append,
                           current_clip=lambda: on_screen[0])

        readout.update(1.0)
        on_screen[0] = Path("second clip.mp4")
        readout.update(2.0)

        assert [hud.modes.video for hud in shown] == ["first clip", "second clip"]

    def test_with_no_clip_up_yet_the_panel_names_none(self):
        shown = []

        _readout(set_console=shown.append).update(1.0)

        assert shown[-1].modes.video == ""

    def test_under_the_broker_there_is_no_drive_of_our_own_to_show(self):
        shown = []

        _readout(set_console=shown.append).blank()

        assert shown == [None]


class TestTheSpanTheTraceIsDrawnOver:
    """Published with the readout, because a funscript Nau draws on this same
    trace has to be sampled over the same stretch and Nau has nowhere else to
    learn it -- two spans would make a handoff look like a jump."""

    @pytest.mark.parametrize("beats_per_loop", [2.0, 4.0, 8.0])
    def test_it_is_one_whole_cycle_at_the_slowest_speed(self, beats_per_loop):
        from player_core.direct_control import MIN_BPM

        shown = []
        _readout(beats_per_loop=beats_per_loop, set_console=shown.append).update(1.0)

        assert shown[-1].drive.trace_seconds == pytest.approx(
            60.0 * beats_per_loop / MIN_BPM)
