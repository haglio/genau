"""Genau's drive readout: what it says, and the controls it carries."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import HudPanel, load_font, text_width

from genau.drive_hud import (
    AMPLITUDE,
    CENTER,
    SECTION_H,
    SECTION_W,
    SPEED,
    DriveHud,
    DriveSection,
    controls,
    label_pair_x,
    publish_drive,
    read_drive,
    track_command,
    track_value,
    tracks,
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


class TestTracks:
    """The bands themselves take a level from where you press in them, so a bar
    is set outright instead of walked to with the marks beside it."""

    @staticmethod
    def _band(hud: DriveHud, axis: str):
        return next(t for t in tracks(PAD, PAD, hud) if t.axis == axis)

    def test_it_offers_a_band_for_each_of_the_three_axes(self):
        assert {t.axis for t in tracks(0, 0, _hud())} == {AMPLITUDE, CENTER, SPEED}

    def test_each_band_covers_the_bar_the_axis_is_drawn_as(self):
        """The trace's band is the trace; the speed band sits between its two
        marks, and the amplitude band between its own."""
        hud = _hud()
        marks = {c.action: c.rect for c in controls(PAD, PAD, hud)}
        speed = self._band(hud, SPEED).rect
        amp = self._band(hud, AMPLITUDE).rect
        down_x, down_y, down_w, _h = marks["genau_speed_down"]

        assert speed[0] >= down_x + down_w
        assert speed[0] + speed[2] <= marks["genau_speed_up"][0]
        assert speed[1] >= down_y - 1
        assert amp[1] >= marks["genau_amplitude_up"][1] + marks["genau_amplitude_up"][3]
        assert amp[1] + amp[3] <= marks["genau_amplitude_down"][1]

    def test_a_press_along_the_speed_bar_asks_for_how_far_along_it_sits(self):
        band = self._band(_hud(), SPEED)
        x, y, w, h = band.rect

        assert track_value(band, x, y + h // 2) == 0
        assert track_value(band, x + (w - 1) // 2, y + h // 2) == 50
        assert track_value(band, x + w - 1, y + h // 2) == 100

    def test_a_press_in_the_trace_asks_for_the_height_it_sits_at(self):
        """The center's dotted line is drawn at its own height across the trace,
        so pressing there is asking for the line to come to the pointer.

        Within a pixel in the middle of the band: the trace is fewer rows tall
        than the hundred values it spans, so a row lands between two of them.
        """
        band = self._band(_hud(), CENTER)
        x, y, w, h = band.rect

        assert track_value(band, x + w // 2, y) == 100
        assert track_value(band, x + w // 2, y + h - 1) == 0
        assert abs(track_value(band, x + w // 2, y + (h - 1) // 2) - 50) <= 1

    def test_a_press_up_the_amplitude_bar_asks_for_a_stroke_that_reaches_it(self):
        """The bar is drawn out from the center both ways, so its ends are the
        handles: pressing where one is asks for the amplitude already set, and
        pressing past it asks for a longer stroke.  Pressing at the center itself
        asks for no stroke at all."""
        band = self._band(_hud(amplitude=50, center=50), AMPLITUDE)
        x, y, w, h = band.rect
        top_of_bar = y + round(0.25 * (h - 1))

        assert abs(track_value(band, x + w // 2, top_of_bar) - 50) <= 1
        assert track_value(band, x + w // 2, y) == 100
        assert track_value(band, x + w // 2, y + h - 1) == 100
        assert abs(track_value(band, x + w // 2, y + (h - 1) // 2)) <= 2

    def test_the_amplitude_bar_mirrors_about_wherever_the_center_is(self):
        """A stroke centered low reaches the top of the bar only by growing to the
        full range and back, so the same press means different amplitudes."""
        low = self._band(_hud(center=25), AMPLITUDE)
        x, y, w, _h = low.rect

        assert track_value(low, x + w // 2, y) == 100

    def test_a_press_beyond_a_band_reads_as_its_nearer_end(self):
        """A drag that wanders off the bar goes on setting it rather than stopping
        dead at the edge, the way every slider behaves."""
        band = self._band(_hud(), SPEED)
        x, y, w, h = band.rect

        assert track_value(band, x - 400, y + h // 2) == 0
        assert track_value(band, x + w + 400, y + h // 2) == 100

    def test_a_press_posts_the_set_command_fun_time_already_routes(self):
        band = self._band(_hud(), SPEED)
        x, y, _w, h = band.rect

        assert track_command(band, x, y + h // 2) == "genau_speed_0"

    def test_every_band_is_dimmed_while_a_funscript_has_the_device(self):
        """A stroke Genau is not sending cannot be dragged, for the same reason
        its marks cannot be pressed."""
        assert all(t.dim for t in tracks(0, 0, _hud(driving=False)))
        assert not any(t.dim for t in tracks(0, 0, _hud()))

    def test_the_bands_it_offers_all_fall_on_the_block_it_draws(self):
        for center in (0, 50, 100):
            for x, y, w, h in (t.rect for t in tracks(PAD, PAD, _hud(center=center))):
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

    def test_the_speed_bar_runs_in_the_stroke_s_own_blue(self):
        """The trace, the amplitude bar and this are all one thing — the stroke
        Genau is sending — so they are one color.  It was green, which across
        these HUDs means the favorites and the funscripts."""
        hud = _hud(speed=100, waveform=())
        rgb = _rendered(hud).astype(int)[:, :, :3]
        rects = {c.action: c.rect for c in controls(PAD, PAD, hud)}
        down_x, down_y, down_w, down_h = rects["genau_speed_down"]
        up_x = rects["genau_speed_up"][0]
        bar = rgb[down_y + down_h // 2, down_x + down_w + 4:up_x - 4]

        assert ((bar[:, 2] > 150) & (bar[:, 0] < 120)).all()


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
