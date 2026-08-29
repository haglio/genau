from __future__ import annotations

from pathlib import Path

from player_core.direct_control import DirectControlState, WaveformShape
from player_core.cruise_control import CruiseControlState
from genau.clip_advance import ClipAdvanceState
from genau.status_writer import build_status_text, write_status_file


def test_build_status_text_defaults():
    ds = DirectControlState()
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "cruise=0" in text
    assert "shape=sine" in text
    assert "amp_at_max=" in text
    assert "spd_at_min=" in text
    assert "hud=0" in text


def test_build_status_text_cruise_active():
    ds = DirectControlState()
    cs = CruiseControlState(active=True)

    text = build_status_text(ds, cs)

    assert "cruise=1" in text


def test_build_status_text_shape():
    ds = DirectControlState(shape=WaveformShape.TRIANGLE)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "shape=triangle" in text


def test_build_status_text_amp_at_max():
    ds = DirectControlState(amplitude=100)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "amp_at_max=1" in text
    assert "amp_at_min=0" in text


def test_build_status_text_amp_at_min():
    ds = DirectControlState(amplitude=0)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "amp_at_max=0" in text
    assert "amp_at_min=1" in text


def test_build_status_text_spd_at_max():
    ds = DirectControlState(speed=100)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "spd_at_max=1" in text
    assert "spd_at_min=0" in text


def test_build_status_text_spd_at_min():
    ds = DirectControlState(speed=5)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "spd_at_max=0" in text
    assert "spd_at_min=1" in text


def test_build_status_text_ctr_at_limits_given_amplitude():
    # amplitude=100 → half=50 → center clamped to [50, 50]
    ds = DirectControlState(amplitude=100, center=50, intended_center=50)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "ctr_at_max=1" in text
    assert "ctr_at_min=1" in text


def test_build_status_text_ctr_not_at_limits():
    # amplitude=20 → half=10 → center range [10, 90]
    ds = DirectControlState(amplitude=20, center=50, intended_center=50)
    cs = CruiseControlState()

    text = build_status_text(ds, cs)

    assert "ctr_at_max=0" in text
    assert "ctr_at_min=0" in text


def test_build_status_text_hud_active():
    ds = DirectControlState()
    cs = CruiseControlState()

    text = build_status_text(ds, cs, hud_active=True)

    assert "hud=1" in text


def test_build_status_text_hud_inactive():
    ds = DirectControlState()
    cs = CruiseControlState()

    text = build_status_text(ds, cs, hud_active=False)

    assert "hud=0" in text


def test_write_status_file_creates_file(tmp_path: Path):
    ds = DirectControlState()
    cs = CruiseControlState()
    path = tmp_path / "genau_status.txt"

    write_status_file(path, ds, cs)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "cruise=0" in text
    assert "shape=sine" in text


def test_write_status_file_skips_when_unchanged(tmp_path: Path):
    ds = DirectControlState()
    cs = CruiseControlState()
    path = tmp_path / "genau_status.txt"

    assert write_status_file(path, ds, cs) is True  # first write
    written_at = path.stat().st_mtime_ns

    assert write_status_file(path, ds, cs) is False  # no change
    assert path.stat().st_mtime_ns == written_at, "the file was rewritten anyway"


def test_build_status_text_reports_the_clip_held_by_default():
    text = build_status_text(DirectControlState(), CruiseControlState())

    assert "locked=1" in text


def test_build_status_text_reports_a_released_clip():
    aa = ClipAdvanceState(locked=False)

    text = build_status_text(DirectControlState(), CruiseControlState(), clip_advance=aa)

    assert "locked=0" in text


def test_build_status_text_names_the_clip_on_screen():
    """The one thing about Genau an orchestrator cannot work out for itself:
    which clip is up, so a reopened session can be pointed back at it."""
    text = build_status_text(
        DirectControlState(), CruiseControlState(), clip=Path("C:/clips/alpha.mp4"),
    )

    assert "clip=C:\\clips\\alpha.mp4" in text or "clip=C:/clips/alpha.mp4" in text


def test_build_status_text_names_no_clip_before_one_is_up():
    """Genau publishes from its refresh loop, which can run a tick before the
    first clip is decoded; an empty value reads as nothing to come back to."""
    text = build_status_text(DirectControlState(), CruiseControlState())

    assert "clip=\n" in text
