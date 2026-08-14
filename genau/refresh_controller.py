from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

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
        show_window,
        hide_window,
        set_loading_text,
        logger,
        log_name: str,
        now_source=time.monotonic,
        consume_command=consume_command_file,
        read_paused_state=None,
        direct_state=None,
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
        self.show_window = show_window
        self.hide_window = hide_window
        self.set_loading_text = set_loading_text
        self.logger = logger
        self.log_name = log_name
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
        self._prev_hud_active: bool = hud_state["active"] if hud_state is not None else False
        self.window_visible = False
        self._prev_playing: bool | None = None

    def refresh(self) -> None:
        try:
            self._refresh_once()
        except Exception as exc:
            self.logger.exception("refresh failed")

    def _refresh_once(self) -> None:
        now = self.now_source()
        self.loader.adopt_loaded_clip_if_ready()
        self.loader.adopt_prefetch_if_ready()
        self.selection.adopt_pending_clip()

        shared = read_shared_state_snapshot(self.state)

        direct_active = self.direct_state is not None and not shared.auto_active

        if direct_active:
            if self.cruise_control is not None:
                from player_core.cruise_control import tick_cruise_control
                tick_cruise_control(self.direct_state, self.cruise_control, now)
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

        self.window_visible = self.notifier.sync_window_visibility(
            desired_visible=shared.visible if self.direct_state is None else True,
            window_visible=self.window_visible,
            current_clip_path=self.renderer.current_clip_path,
            show_window=self.show_window,
            hide_window=self.hide_window,
        )

        if shared.error and self.direct_state is None:
            return

        loop_duration = update_engine(
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

        if self.tcode_sender is not None and direct_active and self.direct_state.playing:
            # Genau taking the device back.  The flip landed in a previous tick's
            # command batch, so this is the first tick it sends on — and it has
            # to be told before it does, not after the edge is noticed further
            # down, or the jump it is meant to smooth has already gone out.
            if self._prev_playing is False:
                self.tcode_sender.take_over()
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if direct_active:
            self._update_console(now)
        elif self.direct_state is not None:
            self.set_console(None)

        prev_playing = self._prev_playing
        if self.direct_state is not None:
            if prev_playing is None:
                prev_playing = self.direct_state.playing

        for cmd in self.consume_command(self.command_file, logger=self.logger):
            apply_runtime_command(
                cmd,
                engine=self.engine,
                rh_paused=self.rh_paused,
                step_clip=self.selection.step,
                discard_clip=self.selection.discard_current,
                direct_state=self.direct_state,
                cruise_control_state=self.cruise_control,
                clip_advance_state=self.clip_advance,
                stop_event=self.stop_event,
                hud_state=self.hud_state,
                display_state=self.display_state,
                set_volume=self.set_volume,
            )

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

        if self.direct_state is not None:
            now_playing = self.direct_state.playing
            if (self.tcode_sender is not None
                    and prev_playing is True and not now_playing):
                # Losing the device — Hybrid's funscript turn, or a plain
                # pause: rest the stroke on the foot of its swing now, so the
                # readout published through the stop shows the stroke that will
                # actually resume, and the resume rises out of the park instead
                # of lunging to wherever the swing froze.
                self.tcode_sender.rest_at_bottom()
            if self.broker_cmd_file is not None and now_playing != prev_playing:
                self.broker_cmd_file.write_text(
                    "RESUME" if now_playing else "PARK", encoding="utf-8",
                )
            # Remembered whether or not there is a broker to tell: the T-Code
            # sender reads this edge too, to glide onto a device a funscript has
            # been holding, and that is true with no broker file configured.
            self._prev_playing = now_playing

        active_entry = self.renderer.current_clip_entry()

        if active_entry and active_entry["frames"]:
            frame_count = len(active_entry["frames"])
            if direct_active:
                from player_core.direct_control import display_phase_for_position
                display_phase = display_phase_for_position(
                    self.engine.phase, self.direct_state.shape,
                )
            else:
                display_phase = self.engine.phase
            display_index = display_index_for_phase(
                phase=display_phase,
                frame_count=frame_count,
                auto_active=auto_active,
                current_frame_index=self.renderer.current_frame_index,
            )
            self.renderer.display_frame(display_index)

        # Show or clear the loading overlay
        pending = self.selection.pending_clip_name
        self.set_loading_text(f"Loading {pending}" if pending else None)

        self.selection.request_nearby_prefetch()

        if self.direct_state is not None:
            self.present_scene()

        if self.direct_state is not None and self.cruise_control is not None:
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

    def _build_drive_hud(self) -> DriveHud:
        from player_core.direct_control import MAX_SPEED, MIN_BPM, MIN_SPEED, sample_waveform

        ds = self.direct_state
        position = 0
        start_phase = 0.0
        if self.tcode_sender is not None:
            position = self.tcode_sender.current_position()
            start_phase = self.tcode_sender.stroke_phase

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
            waveform=tuple(sample_waveform(
                ds.shape, ds.amplitude, ds.center, TRACE_SAMPLES,
                start_phase=start_phase,
                phase_range=phase_per_second * display_seconds,
            )),
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
