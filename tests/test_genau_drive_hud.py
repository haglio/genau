"""Genau's drive readout: what it says, and the controls it carries."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import HudPanel, load_font, text_width

from genau.drive_hud import (
    SECTION_H,
    SECTION_W,
    DriveHud,
    DriveSection,
    controls,
    label_pair_x,
    publish_drive,
    read_drive,
)

PAD = 10


def _hud(**overrides) -> DriveHud:
    base = dict(speed=50, amplitude=80, center=50, shape="sine", position=5000,
                waveform=tuple(0.5 + 0.4 * np.sin(i / 6) for i in range(80)))
    base.update(overrides)
    return DriveHud(**base)


def _rendered(hud: DriveHud) -> np.ndarray:
    panel = HudPanel(SECTION_W + 2 * PAD, SECTION_H + 2 * PAD)
    DriveSection().draw(panel.draw, PAD, PAD, hud)
    return np.asarray(panel.image)


class TestControls:
    """Each axis is one object: its controls, its bar and its number together."""

    def test_it_offers_every_axis_a_way_up_and_down(self):
        actions = {control.action for control in controls(0, 0, _hud())}

        assert actions == {
            "genau_speed_down", "genau_speed_up",
            "genau_amplitude_up", "genau_amplitude_down",
            "genau_center_up", "genau_center_down",
        }

    def test_every_axis_is_moved_by_the_same_pair_of_marks(self):
        """Triangles on two axes and −/+ on the third read as two kinds of
        control for three things that are the same kind."""
        by_action = {c.action: c.glyph for c in controls(0, 0, _hud())}

        assert {by_action[a] for a in
                ("genau_speed_up", "genau_amplitude_up", "genau_center_up")} == {"+"}
        assert {by_action[a] for a in
                ("genau_speed_down", "genau_amplitude_down", "genau_center_down")} == {"−"}

    def test_the_speed_controls_sit_below_the_trace(self):
        """Speed is out from between centre and amplitude, under the trace, so the
        three axes do not crowd one band."""
        by_action = {c.action: c.rect for c in controls(0, 0, _hud())}
        wave_bottom = max(by_action["genau_amplitude_down"][1] + by_action["genau_amplitude_down"][3],
                          by_action["genau_center_down"][1])

        assert by_action["genau_speed_down"][1] >= wave_bottom
        assert by_action["genau_speed_up"][1] >= wave_bottom

    def test_a_mark_at_its_limit_is_dimmed(self):
        """The flag on the readout says the axis has run out of range, so the mark
        that would do nothing is greyed — the console then drops it from the hit
        targets, the same as any dimmed control."""
        by_action = {c.action: c for c in controls(0, 0, _hud(spd_at_max=True, amp_at_min=True))}

        assert by_action["genau_speed_up"].dim is True
        assert by_action["genau_speed_down"].dim is False
        assert by_action["genau_amplitude_down"].dim is True

    def test_the_centre_marks_follow_the_line(self):
        """They sit beside the centre's dotted line, so they move up the panel as
        the centre rises."""
        low = {c.action: c.rect for c in controls(0, 0, _hud(center=20))}
        high = {c.action: c.rect for c in controls(0, 0, _hud(center=80))}

        assert high["genau_center_up"][1] < low["genau_center_up"][1]

    def test_the_marks_it_offers_all_fall_on_the_block_it_draws(self):
        """Drawing and hit-testing place the marks from one geometry, so a press
        lands on what is on screen — at either end of the centre's travel."""
        for center in (0, 50, 100):
            for x, y, w, h in (c.rect for c in controls(PAD, PAD, _hud(center=center))):
                assert PAD <= x and x + w <= PAD + SECTION_W
                assert PAD <= y and y + h <= PAD + SECTION_H


class TestReadout:
    def test_it_fills_the_block_it_declares(self):
        rgb = _rendered(_hud(speed=62, center=45, amplitude=80))

        assert rgb.shape == (SECTION_H + 2 * PAD, SECTION_W + 2 * PAD, 4)
        assert (rgb[:, :, 3] > 0).mean() > 0.5

    def test_a_bigger_stroke_draws_a_bigger_bar(self):
        def blue(hud):
            rgb = _rendered(hud).astype(int)[:, :, :3]
            return int(((rgb[:, :, 2] > 150) & (rgb[:, :, 0] < 120)).sum())

        assert blue(_hud(amplitude=90, waveform=())) > blue(_hud(amplitude=20, waveform=()))


class TestPublishing:
    """In Hybrid the readout is drawn by Nau, so Genau says it instead of drawing it."""

    def test_a_published_readout_reads_back_whole_including_its_limits(self, tmp_path):
        hud = _hud(shape="sawtooth", advance_interval=7,
                   spd_at_max=True, ctr_at_min=True)
        path = tmp_path / "genau_drive.txt"

        assert publish_drive(path, hud) is True
        read = read_drive(path)

        assert (read.speed, read.amplitude, read.center) == (hud.speed, hud.amplitude, hud.center)
        assert (read.shape, read.advance_interval) == ("sawtooth", 7)
        assert (read.spd_at_max, read.ctr_at_min) == (True, True)
        assert np.allclose(read.waveform, hud.waveform, atol=5e-4)

    def test_a_readout_that_has_been_over_the_wire_survives_going_again(self, tmp_path):
        path = tmp_path / "genau_drive.txt"
        publish_drive(path, _hud())
        once = read_drive(path)

        publish_drive(path, once)

        assert read_drive(path) == once

    def test_a_missing_or_torn_read_keeps_what_the_reader_has(self, tmp_path):
        path = tmp_path / "genau_drive.txt"

        assert read_drive(path) is None

        path.write_text("speed=40\namplit", encoding="utf-8")
        assert read_drive(path) is None


class TestLabelPair:
    def test_a_pair_is_placed_as_one_unit(self):
        font = load_font(8)

        key_x, value_x = label_pair_x(font, "Speed", "62", left=10)

        assert key_x == 10
        assert value_x >= key_x + text_width(font, "Speed")
