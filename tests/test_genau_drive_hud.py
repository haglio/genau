"""Genau's drive readout: what it says, and the controls it carries."""
from __future__ import annotations

import numpy as np
from player_core.hud_panel import (
    BLUE,
    GREEN,
    TEXT_MUTED,
    HudPanel,
    load_font,
    text_width,
)

from genau.drive_hud import (
    AMPLITUDE,
    CENTER,
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NOTHING,
    SECTION_H,
    SECTION_W,
    SPEED,
    TRACE_ONLY_SIZE,
    DriveHud,
    DriveSection,
    blend,
    section_size,
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
        assert all(t.dim for t in tracks(0, 0, _hud(driven=DRIVEN_BY_FUNSCRIPT)))
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


class TestWhoseStroke:
    """The trace is a picture of what the device is being sent, so it is drawn in
    the color of whoever is sending it — and drawn still when nobody is."""

    @staticmethod
    def _line_colors(hud: DriveHud) -> set[tuple[int, int, int]]:
        """Every color the trace's own line is drawn in, panel and ruler aside."""
        rgb = _rendered(hud).astype(int)[:, :, :3]
        return {tuple(pixel) for row in rgb for pixel in row} - {(0, 0, 0)}

    def test_genau_s_own_stroke_is_blue(self):
        assert BLUE in self._line_colors(_hud(driven=DRIVEN_BY_GENAU))

    def test_a_funscript_s_stroke_is_green(self):
        """Green is what the funscripts own everywhere else on these HUDs."""
        assert GREEN in self._line_colors(_hud(driven=DRIVEN_BY_FUNSCRIPT))

    def test_a_stroke_nobody_is_sending_is_the_muted_grey_of_a_dead_control(self):
        """The readout is switched off whole rather than a live trace sitting in
        the middle of dead furniture."""
        assert TEXT_MUTED in self._line_colors(_hud(driven=DRIVEN_BY_NOTHING))

    def test_only_genau_s_stroke_carries_the_centre_ruler(self):
        """The dotted line says "the stroke swings about here", which is Genau's
        own idea — a claim about a stroke a funscript is not making."""
        genau = _rendered(_hud(driven=DRIVEN_BY_GENAU, waveform=()))
        script = _rendered(_hud(driven=DRIVEN_BY_FUNSCRIPT, waveform=()))

        assert not np.array_equal(genau, script)

    def test_only_genau_s_stroke_leaves_its_controls_live(self):
        for driven in (DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_NOTHING):
            assert all(c.dim for c in controls(0, 0, _hud(driven=driven)))
        assert not all(c.dim for c in controls(0, 0, _hud(driven=DRIVEN_BY_GENAU)))


class TestTraceOnly:
    """In Nau there is no Genau behind the screen: its levels describe a stroke
    nothing is making, and no control on them could reach one."""

    def test_it_is_only_as_big_as_the_trace(self):
        assert section_size(trace_only=True) == TRACE_ONLY_SIZE
        assert section_size() == (SECTION_W, SECTION_H)

    def test_it_offers_no_marks_and_no_bands(self):
        hud = _hud()

        assert controls(0, 0, hud, trace_only=True) == []
        assert tracks(0, 0, hud, trace_only=True) == []

    def test_it_draws_the_trace_and_nothing_beside_it(self):
        """Measured against the bare slab, so what counts is what the readout
        put there rather than what the panel under it already had."""
        bare = np.asarray(HudPanel(SECTION_W + 2 * PAD, SECTION_H + 2 * PAD).image)
        panel = HudPanel(SECTION_W + 2 * PAD, SECTION_H + 2 * PAD)
        DriveSection().draw(panel.draw, PAD, PAD, _hud(), trace_only=True)
        touched = (np.asarray(panel.image) != bare).any(axis=2)
        width, height = TRACE_ONLY_SIZE

        assert touched[:, PAD + width + 2:].sum() == 0
        assert touched[PAD + height + 2:, :].sum() == 0
        assert touched[PAD:PAD + height, PAD:PAD + width].any()


class TestBlend:
    """The device glides from one driver's stroke onto the other's, and the trace
    spends that same time on its way from one color to the other."""

    def test_the_ends_are_the_two_colors_themselves(self):
        assert blend(BLUE, GREEN, 0.0) == BLUE
        assert blend(BLUE, GREEN, 1.0) == GREEN

    def test_the_middle_is_between_them(self):
        assert blend((0, 0, 0), (100, 200, 40), 0.5) == (50, 100, 20)

    def test_it_cannot_run_past_either_end(self):
        assert blend(BLUE, GREEN, 5.0) == GREEN
        assert blend(BLUE, GREEN, -5.0) == BLUE


class TestPublishedSpan:
    def test_the_trace_s_span_travels_with_it(self, tmp_path):
        """Nau samples a funscript over the same stretch Genau's stroke covers,
        and has nowhere else to learn what that is — two spans would make a
        handoff look like a jump."""
        path = tmp_path / "genau_drive.txt"
        publish_drive(path, _hud(trace_seconds=7.5))

        assert read_drive(path).trace_seconds == 7.5

    def test_a_file_from_before_it_was_published_keeps_the_default(self, tmp_path):
        path = tmp_path / "genau_drive.txt"
        publish_drive(path, _hud())
        text = path.read_text(encoding="utf-8")
        path.write_text(
            "\n".join(line for line in text.splitlines()
                      if not line.startswith("trace_seconds")),
            encoding="utf-8")

        assert read_drive(path).trace_seconds == DriveHud.trace_seconds
