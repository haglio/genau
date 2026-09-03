"""What Genau draws over its clip, and what it says for Nau to draw.

Two publications of the drive, on two cadences.  The readout's trace scrolls, so
it cannot wait on a change the way the status file does and is throttled
instead; the console around it -- mode, OSR2, broker -- moves a few times a
minute and is re-read far less often than the readout is rebuilt.  In Hybrid the
panel belongs to Nau's console, because the controls that move these numbers are
up there, and Genau's window is only the transparent layer driving the device.
"""
from __future__ import annotations

from pathlib import Path

from player_core.console import ConsoleModel, read_console
from player_core.console_hud import ConsoleHud, ModeHud
from player_core.drive_readout import TRACE_SAMPLES, DriveHud, publish_drive

from .controls import GenauControls
from .limits import control_limits

# How often the drive readout goes out for Nau to draw.  Its trace scrolls, so it
# cannot wait on a change the way the status file does -- 25/s is well under
# Genau's refresh rate and well over what reads as smooth.
_DRIVE_PUBLISH_INTERVAL_S = 0.04

# How often Genau re-reads the console Fun Time publishes.  Its own drive numbers
# scroll every tick, but the mode / OSR2 / broker around them move a few times a
# minute, so the file is read far less often than the readout is rebuilt.
_CONSOLE_READ_INTERVAL_S = 0.2


class DriveReadout:
    def __init__(
        self,
        *,
        controls: GenauControls,
        beats_per_loop: float,
        tcode_sender=None,
        drive_file: Path | None = None,
        console_file: Path | None = None,
        set_console=None,
        current_clip=lambda: None,
    ):
        self.direct_state = controls.direct_state
        self.cruise_control = controls.cruise_control_state
        self.clip_advance = controls.clip_advance_state
        self.beats_per_loop = beats_per_loop
        self.tcode_sender = tcode_sender
        self.drive_file = drive_file
        self.console_file = console_file
        self.set_console = set_console or (lambda _console: None)
        self.current_clip = current_clip
        self._last_drive_publish = 0.0
        # The console around the readout -- mode, OSR2, broker -- as Fun Time
        # published it; genau mode defaults it to itself so a standalone Genau
        # still draws a sensible panel with no file behind it.
        self._console_model = ConsoleModel(mode="genau")
        self._last_console_read = 0.0

    def blank(self) -> None:
        """Under the broker there is no drive of Genau's own to show."""
        self.set_console(None)

    def update(self, now: float) -> None:
        """Build the drive readout, publish it for Nau, and draw the whole console
        for Genau's own window."""
        hud = self._build_drive_hud()
        self._publish_drive(hud, now)
        if now - self._last_console_read >= _CONSOLE_READ_INTERVAL_S and self.console_file:
            self._last_console_read = now
            published = read_console(self.console_file)
            if published is not None:
                self._console_model = published
        # The same top block Nau draws: the status line, and the clip on screen
        # under it.  Genau has no Nau playlist behind its screen and so none of
        # the modes Nau reports — its own two states, the lock and the pace an
        # unheld clip moves on at, are read off the console and the drive readout
        # by ConsoleHud.status_line, so there is nothing to hand it here.
        clip = self.current_clip()
        self.set_console(ConsoleHud(
            modes=ModeHud(video=Path(clip).stem if clip else ""),
            console=self._console_model, drive=hud,
        ))

    def _build_drive_hud(self) -> DriveHud:
        from player_core.direct_control import MIN_BPM, POSITION_MAX

        ds = self.direct_state
        position = 0
        start_phase = 0.0
        let_go = None
        if self.tcode_sender is not None:
            position = self.tcode_sender.current_position()
            start_phase = self.tcode_sender.stroke_phase
            if self.tcode_sender.let_go_position is not None:
                # The height the device was handed over at, 0-1 — the one number
                # the trace cannot recompute once the phase has rested.
                let_go = self.tcode_sender.let_go_position / POSITION_MAX

        phase_per_second = ds.bpm / 60.0 / self.beats_per_loop if ds.bpm > 0 else 1.0
        # Show enough time that one whole cycle is visible at the slowest speed.
        # Published with the readout, because a funscript drawn on this same trace
        # has to be sampled over the same stretch and Nau has nowhere else to
        # learn it — two spans would make a handoff look like a jump.
        display_seconds = 60.0 * self.beats_per_loop / MIN_BPM

        # Which arrow would do nothing — the readout dims those.  The same six
        # the status file publishes, from the same answer.
        limits = control_limits(ds)
        return DriveHud(
            speed=ds.speed,
            amplitude=ds.amplitude,
            center=ds.center,
            shape=ds.shape.value,
            position=position,
            advance_interval=(
                self.clip_advance.interval if self.clip_advance else 0
            ),
            spd_at_max=limits.spd_at_max,
            spd_at_min=limits.spd_at_min,
            amp_at_max=limits.amp_at_max,
            amp_at_min=limits.amp_at_min,
            ctr_at_max=limits.ctr_at_max,
            ctr_at_min=limits.ctr_at_min,
            trace_seconds=display_seconds,
            let_go=let_go,
            waveform=tuple(self._trace(
                display_seconds, start_phase, phase_per_second)),
        )

    def _trace(self, display_seconds: float, start_phase: float,
               phase_per_second: float) -> list[float]:
        """The stroke sampled forward as the readout draws it — and as Nau
        draws a funscript over it, which is why both are the same span.

        Cruise control's stroke cannot be sampled by walking one phase: its
        waves each run at their own speed, and every parameter of every one of
        them is moving over a span this long. It is walked in time instead.
        """
        from player_core import wave_stack
        from player_core.direct_control import sample_waveform

        if self.cruise_control is not None and self.cruise_control.stack:
            return wave_stack.trace(
                self.cruise_control.stack, self.cruise_control.clock,
                TRACE_SAMPLES, display_seconds)
        ds = self.direct_state
        return sample_waveform(
            ds.shape, ds.amplitude, ds.center, TRACE_SAMPLES,
            start_phase=start_phase,
            phase_range=phase_per_second * display_seconds,
        )

    def _publish_drive(self, hud: DriveHud, now: float) -> None:
        """Say the readout for Nau to draw, at a fraction of the refresh rate.

        In Hybrid this panel belongs to Nau's console — the controls that move
        these numbers are up there, so the numbers are too — and Genau's window is
        only the transparent layer driving the device.  The trace scrolls, so this
        cannot wait for a change the way the status file does; it is throttled
        instead, well under the refresh rate and well over what the eye reads as
        smooth.
        """
        if self.drive_file is None:
            return
        if now - self._last_drive_publish < _DRIVE_PUBLISH_INTERVAL_S:
            return
        self._last_drive_publish = now
        publish_drive(self.drive_file, hud)
