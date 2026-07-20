"""Genau's drive readout: what it says about the stroke it is sending."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import AMBER, BLUE, load_font, text_width

from genau.drive_hud import (
    PANEL_SIZE,
    DriveHud,
    DriveHudPainter,
    label_pair_x,
    publish_drive,
    read_drive,
    shape_label,
)


def _rgb(bgra: np.ndarray) -> np.ndarray:
    return bgra[:, :, [2, 1, 0]]


def _ink(bgra: np.ndarray, color, *, tolerance: int = 40) -> int:
    """How many pixels are drawn in *color* — how the panel's parts are told
    apart without asserting on exact coordinates."""
    diff = np.abs(_rgb(bgra).astype(int) - np.asarray(color, dtype=int))
    return int((diff.max(axis=2) <= tolerance).sum())


def _hud(**overrides) -> DriveHud:
    base = dict(speed=50, amplitude=80, center=50, shape="sine", position=5000,
                waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(80)))
    base.update(overrides)
    return DriveHud(**base)


class TestShapeLabel:
    def test_names_the_waveform_instead_of_only_drawing_it(self):
        """The old panel drew the wave and never named it, so the shape you had
        cycled to could only be inferred from the trace."""
        assert shape_label("sine") == "Sine"
        assert shape_label("rounded_square") == "Square"
        assert shape_label("sawtooth") == "Sawtooth"
        assert shape_label("triangle") == "Triangle"

    def test_an_unknown_shape_is_titled_rather_than_dropped(self):
        assert shape_label("half_moon") == "Half Moon"


class TestLabelPair:
    """A key and its value placed as one unit, so neither can land on the other."""

    def test_the_value_follows_its_key(self):
        font = load_font(8)

        key_x, value_x = label_pair_x(font, "Speed", "62", left=10)

        assert key_x == 10
        assert value_x >= key_x + text_width(font, "Speed")

    def test_a_right_aligned_pair_ends_at_the_edge_it_was_given(self):
        """The amplitude's pair is wider than the bar it labels, so it hangs off
        that column to the left rather than being squeezed into it — which is how
        "Amp" and its number came to be drawn on top of each other."""
        font = load_font(8)

        key_x, value_x = label_pair_x(font, "Amp", "100", right=222)

        assert value_x + text_width(font, "100") == 222
        assert key_x < value_x

    def test_the_two_pairs_the_panel_draws_do_not_meet(self):
        font = load_font(8)
        width = PANEL_SIZE[0]

        _speed_key, speed_value = label_pair_x(font, "Speed", "100", left=10)
        amp_key, _amp_value = label_pair_x(font, "Amp", "100", right=width - 10)

        assert speed_value + text_width(font, "100") < amp_key


class TestPublishing:
    """In Hybrid the readout is drawn by Nau, so Genau says it instead of drawing it."""

    def test_a_published_readout_reads_back_whole(self, tmp_path):
        hud = _hud(cruise=True, playing=True, shape="sawtooth")
        path = tmp_path / "genau_drive.txt"

        assert publish_drive(path, hud) is True
        read = read_drive(path)

        assert (read.speed, read.amplitude, read.center) == (hud.speed, hud.amplitude, hud.center)
        assert (read.position, read.shape) == (hud.position, hud.shape)
        assert (read.cruise, read.playing) == (True, True)
        # The trace goes over at three decimals — a thousandth of the box it is
        # drawn in, so the rounding is invisible and the line stays short.
        assert np.allclose(read.waveform, hud.waveform, atol=5e-4)

    def test_a_readout_that_has_been_over_the_wire_survives_going_again(self, tmp_path):
        """What Nau holds must publish back to the same bytes, or the reader's
        "has this moved?" comparison sees a change every single tick."""
        path = tmp_path / "genau_drive.txt"
        publish_drive(path, _hud())
        once = read_drive(path)

        publish_drive(path, once)

        assert read_drive(path) == once

    def test_a_missing_or_torn_read_keeps_what_the_reader_has(self, tmp_path):
        """The file is replaced while Nau polls it every frame; a lost race must
        not blank the readout for a frame, so it answers None rather than empty."""
        path = tmp_path / "genau_drive.txt"

        assert read_drive(path) is None

        path.write_text("speed=40\namplit", encoding="utf-8")
        assert read_drive(path) is None

    def test_a_readout_with_no_trace_yet_still_reads_back(self, tmp_path):
        path = tmp_path / "genau_drive.txt"
        publish_drive(path, _hud(waveform=()))

        assert read_drive(path).waveform == ()


class TestPainter:
    def test_paints_the_declared_panel(self):
        bgra = DriveHudPainter().bgra(_hud())

        width, height = PANEL_SIZE
        assert bgra.shape == (height, width, 4)
        assert (bgra[:, :, 3] > 0).mean() > 0.5  # the slab fills it, corners aside

    def test_a_state_that_has_not_moved_is_not_repainted(self):
        """Both hosts redraw at display rate and Pillow cannot keep up, so the
        bitmap has to survive between changes — the same reason Nau's mode panel
        caches."""
        painter = DriveHudPainter()

        first = painter.bgra(_hud())

        assert painter.bgra(_hud()) is first
        assert painter.bgra(_hud(amplitude=20)) is not first

    def test_cruise_says_so_only_while_it_is_holding_the_speed(self):
        painter = DriveHudPainter()

        assert _ink(painter.bgra(_hud(cruise=True)), AMBER) > \
            _ink(DriveHudPainter().bgra(_hud(cruise=False)), AMBER)

    def test_a_bigger_stroke_draws_a_bigger_bar(self):
        """The amplitude bar is the stroke's extent, so it has to grow with it —
        it is the only thing on the panel that says how far the device travels."""
        small = _ink(DriveHudPainter().bgra(_hud(amplitude=20, waveform=())), BLUE)
        large = _ink(DriveHudPainter().bgra(_hud(amplitude=90, waveform=())), BLUE)

        assert large > small

    def test_an_empty_waveform_still_paints(self):
        """Before the first sample there is no trace to draw; the panel is the
        readout, not the trace, so it must stand without one."""
        assert DriveHudPainter().bgra(_hud(waveform=())).shape[2] == 4
