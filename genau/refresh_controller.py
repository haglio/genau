from __future__ import annotations

import time
from pathlib import Path

from player_core.clip_scrub import ClipScrub, scrub_clip
from player_core.file_channel import consume_command_file

from player_core.console import ConsoleModel, read_console
from player_core.console_hud import ConsoleHud, ModeHud

from player_core.drive_readout import TRACE_SAMPLES, DriveHud, publish_drive
from .engine import update_engine
from .refresh_logic import display_index_for_phase, read_shared_state_snapshot
from .runtime_commands import apply_runtime_command
from .status_writer import write_status_file

# How often the drive readout goes out for Nau to draw.  Its trace scrolls, so it
# cannot wait on a change the way the status file does — 25/s is well under
# Genau's refresh rate and well over what reads as smooth.
_DRIVE_PUBLISH_INTERVAL_S = 0.04

# How often Genau re-reads the console Fun Time publishes.  Its own drive numbers
# scroll every tick, but the mode / OSR2 / broker around them move a few times a
# minute, so the file is read far less often than the readout is rebuilt.
_CONSOLE_READ_INTERVAL_S = 0.2


class GenauRefreshController:
    def __init__(
        self,
        *,
        state,
        loader,
        notifier,
        renderer,
        selection,
        engine,
        rh_paused,
        command_file: Path,
        paused_file: Path,
        beats_per_loop: float,
        bpm_smoothing: float,
        sync_strength: float,
        set_loading_text,
        logger,
        direct_state,
        now_source=time.monotonic,
        consume_command=consume_command_file,
        read_paused_state=None,
        tcode_sender=None,
        cruise_control=None,
        clip_advance=None,
        broker_cmd_file: Path | None = None,
        drive_file: Path | None = None,
        console_file: Path | None = None,
        set_console=None,
        present_scene=None,
        stop_event=None,
        hud_state=None,
        set_hud_mode=None,
        set_blank=None,
        display_state=None,
        set_volume=None,
        reorder_clips=None,
    ):
        self.state = state
        self.loader = loader
        self.notifier = notifier
        self.renderer = renderer
        self.selection = selection
        self.engine = engine
        self.rh_paused = rh_paused
        self.command_file = command_file
        self.paused_file = paused_file
        self.beats_per_loop = beats_per_loop
        self.bpm_smoothing = bpm_smoothing
        self.sync_strength = sync_strength
        self.set_loading_text = set_loading_text
        self.logger = logger
        self.now_source = now_source
        self.consume_command = consume_command
        self.read_paused_state = read_paused_state or (lambda _path, logger=None: False)
        self.direct_state = direct_state
        self.tcode_sender = tcode_sender
        self.cruise_control = cruise_control
        self.clip_advance = clip_advance
        self.broker_cmd_file = broker_cmd_file
        self.drive_file = drive_file
        self.console_file = console_file
        self._last_drive_publish = 0.0
        # The console around the readout — mode, OSR2, broker — as Fun Time
        # published it; genau mode defaults it to itself so a standalone Genau
        # still draws a sensible panel with no file behind it.
        self._console_model = ConsoleModel(mode="genau")
        self._last_console_read = 0.0
        self.set_console = set_console or (lambda _console: None)
        self.present_scene = present_scene or (lambda: None)
        self.stop_event = stop_event
        self.hud_state = hud_state
        self.set_hud_mode = set_hud_mode or (lambda _active: None)
        self.set_blank = set_blank or (lambda _blank: None)
        self.display_state = display_state
        self.set_volume = set_volume or (lambda _level, _muted: None)
        self.reorder_clips = reorder_clips
        self._prev_hud_active: bool = hud_state["active"] if hud_state is not None else False
        # Seeded from the state itself, so a PAUSE queued before the first
        # refresh reads as a real falling edge against the state the controller
        # was built in.
        self._prev_playing: bool = direct_state.playing
        # Which half of the clip is showing, and what is known about the end
        # the stroke is at — see :meth:`_scrub_the_clip`.
        self._scrub = ClipScrub()

    def refresh(self) -> None:
        try:
            self._refresh_once()
        except Exception:
            self.logger.exception("refresh failed")

    def _refresh_once(self) -> None:
        now = self.now_source()
        self.loader.adopt_loaded_clip_if_ready()
        self.loader.adopt_prefetch_if_ready()
        self.selection.adopt_pending_clip()

        # Drained FIRST, before anything below reads the state the commands
        # mutate, and before this tick's stroke command goes out.
        for cmd in self.consume_command(self.command_file, logger=self.logger):
            apply_runtime_command(
                cmd,
                engine=self.engine,
                rh_paused=self.rh_paused,
                step_clip=self.selection.step,
                discard_clip=self.selection.discard_current,
                direct_state=self.direct_state,
                cruise_control_state=self.cruise_control,
                set_stroke_phase=(
                    self.tcode_sender.set_stroke_phase
                    if self.tcode_sender is not None else None
                ),
                clip_advance_state=self.clip_advance,
                stop_event=self.stop_event,
                hud_state=self.hud_state,
                display_state=self.display_state,
                set_volume=self.set_volume,
                reorder_clips=self.reorder_clips,
            )

        shared = read_shared_state_snapshot(self.state)

        direct_active = not shared.auto_active

        if direct_active:
            if self.cruise_control is not None:
                from player_core.cruise_control import tick_cruise_control
                # The phase is only read on the tick that draws the waves: they
                # all start where the stroke already is, so taking over cannot
                # be felt.
                tick_cruise_control(
                    self.direct_state, self.cruise_control, now,
                    phase=(self.tcode_sender.stroke_phase
                           if self.tcode_sender is not None else 0.0),
                )
            if self.clip_advance is not None:
                from .clip_advance import tick_clip_advance
                # The interval is timed against the clip actually on screen — a
                # decoded, rendering one — so a slow load can't make a short
                # interval fire repeatedly and stack switches that never play.
                entry = self.renderer.current_clip_entry()
                on_screen_clip = (
                    self.renderer.current_clip_path if entry and entry.get("frames") else None
                )
                tick_clip_advance(
                    self.clip_advance,
                    now,
                    playing=self.direct_state.playing,
                    on_screen_clip=on_screen_clip,
                    step_clip=self.selection.step,
                )
            auto_active = self.direct_state.playing
            raw_bpm = self.direct_state.bpm
            paused = not self.direct_state.playing
            sync_pulse_id = 0
        else:
            self.rh_paused["value"] = self.read_paused_state(self.paused_file, logger=self.logger)
            auto_active = shared.auto_active
            raw_bpm = shared.raw_bpm
            paused = self.rh_paused["value"]
            sync_pulse_id = shared.sync_pulse_id

        # Said every tick and heard once: the notifier drops a repeat.  The
        # clip that goes with it is the clip selection's to announce, and it
        # already has by the time the first tick runs.
        self.notifier.notify_visible(True)

        update_engine(
            self.engine,
            now=now,
            auto_active=auto_active,
            raw_bpm=raw_bpm,
            sync_pulse_id=sync_pulse_id,
            beats_per_loop=self.beats_per_loop,
            bpm_smoothing=self.bpm_smoothing,
            sync_strength=self.sync_strength,
            paused=paused,
        )

        # The device changing hands, both directions, seen the same tick the
        # command landed (the drain above runs first).  Symmetric on purpose:
        # the falling edge latches where the device was and rests the swing;
        # the rising edge arms the climb out of the park.
        now_playing = self.direct_state.playing
        prev_playing = self._prev_playing
        if self.tcode_sender is not None:
            if now_playing and not prev_playing:
                self.tcode_sender.take_over()
            elif prev_playing and not now_playing:
                self.tcode_sender.hand_over()
        if self.broker_cmd_file is not None and now_playing != prev_playing:
            self.broker_cmd_file.write_text(
                "RESUME" if now_playing else "PARK", encoding="utf-8",
            )
        self._prev_playing = now_playing

        if self.tcode_sender is not None and direct_active and self.direct_state.playing:
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if direct_active:
            self._update_console(now)
        else:
            self.set_console(None)

        if self.hud_state is not None:
            hud_active = self.hud_state["active"]
            if hud_active != self._prev_hud_active:
                self.set_hud_mode(hud_active)
                self._prev_hud_active = hud_active

        # Paint black only while an orchestrator has told us we aren't the active
        # display.  Deliberately NOT keyed off playback: a paused hand is normal
        # (standalone boots paused, and OmniPause freezes it mid-session), and
        # blanking on that hides the clip the user is looking at.
        display_active = self.display_state["active"] if self.display_state is not None else True
        self.set_blank(not display_active)

        active_entry = self.renderer.current_clip_entry()

        if active_entry and active_entry["frames"]:
            frame_count = len(active_entry["frames"])
            if direct_active:
                display_phase = self._scrub_the_clip(frame_count)
            else:
                display_phase = self.engine.phase
            display_index = display_index_for_phase(
                phase=display_phase,
                frame_count=frame_count,
                auto_active=auto_active,
                current_frame_index=self.renderer.current_frame_index,
            )
            self.renderer.display_frame(display_index)

        pending = self.selection.pending_clip_name
        self.set_loading_text(f"Loading {pending}" if pending else None)

        self.selection.request_nearby_prefetch()

        self.present_scene()

        if self.cruise_control is not None:
            status_path = self.command_file.parent / "genau_status.txt"
            hud_on = self.hud_state["active"] if self.hud_state is not None else False
            write_status_file(
                status_path,
                self.direct_state,
                self.cruise_control,
                clip_advance=self.clip_advance,
                hud_active=hud_on,
                clip=self.renderer.current_clip_path,
            )

    def _update_console(self, now: float) -> None:
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
        clip = self.renderer.current_clip_path
        self.set_console(ConsoleHud(
            modes=ModeHud(video=Path(clip).stem if clip else ""),
            console=self._console_model, drive=hud,
        ))

    def _scrub_the_clip(self, frame_count: int) -> float:
        """How far through the clip to be: exactly as far as the device is up
        its own axis.

        The frame is the picture of where the device is, which is the same
        number the readout's dot draws — so the two cannot drift apart, and a
        stroke that only works part of the axis only ever shows that part of the
        clip. :mod:`player_core.clip_scrub` is the whole rule, including which
        half is showing and when that may change.
        """
        from player_core.direct_control import POSITION_MAX

        if self.tcode_sender is None:
            return self.engine.phase
        return scrub_clip(
            self._scrub,
            self.tcode_sender.current_position() / POSITION_MAX,
            frame_count,
        )

    def _build_drive_hud(self) -> DriveHud:
        from player_core.direct_control import (
            MAX_SPEED, MIN_BPM, MIN_SPEED, POSITION_MAX,
        )

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

        # Which arrow would do nothing — the readout dims those.  The centre's
        # range is what the amplitude leaves it (it cannot push a stroke off the
        # top or bottom of the device), the same clamp the status file uses.
        half = ds.amplitude // 2
        return DriveHud(
            speed=ds.speed,
            amplitude=ds.amplitude,
            center=ds.center,
            shape=ds.shape.value,
            position=position,
            advance_interval=(
                self.clip_advance.interval if self.clip_advance else 0
            ),
            spd_at_max=ds.speed >= MAX_SPEED,
            spd_at_min=ds.speed <= MIN_SPEED,
            amp_at_max=ds.amplitude >= 100,
            amp_at_min=ds.amplitude <= 0,
            ctr_at_max=ds.center >= 100 - half,
            ctr_at_min=ds.center <= half,
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
