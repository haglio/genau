from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from player_core.file_channel import consume_command_file

from .engine import update_engine
from .refresh_logic import display_index_for_phase, read_shared_state_snapshot
from .runtime_commands import apply_runtime_command
from .status_writer import write_status_file


@dataclass
class DirectOverlayData:
    speed: int
    bpm: float
    amplitude: int
    center: int
    waveform_points: list[float]
    position: int
    cruise_active: bool
    phase_per_second: float = 1.0
    display_seconds: float = 4.0


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
        broker_cmd_file: Path | None = None,
        set_direct_overlay=None,
        present_scene=None,
        stop_event=None,
        hud_state=None,
        set_hud_mode=None,
        set_blank=None,
        display_state=None,
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
        self.broker_cmd_file = broker_cmd_file
        self.set_direct_overlay = set_direct_overlay or (lambda _data: None)
        self.present_scene = present_scene or (lambda: None)
        self.stop_event = stop_event
        self.hud_state = hud_state
        self.set_hud_mode = set_hud_mode or (lambda _active: None)
        self.set_blank = set_blank or (lambda _blank: None)
        self.display_state = display_state
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
                from .cruise_control import tick_cruise_control
                tick_cruise_control(self.direct_state, self.cruise_control, now, step_clip=self.selection.step)
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
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if direct_active:
            self._update_direct_overlay()
        elif self.direct_state is not None:
            self.set_direct_overlay(None)

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
                direct_state=self.direct_state,
                cruise_control_state=self.cruise_control,
                stop_event=self.stop_event,
                hud_state=self.hud_state,
                display_state=self.display_state,
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

        if self.direct_state is not None and self.broker_cmd_file is not None:
            now_playing = self.direct_state.playing
            if now_playing != prev_playing:
                self.broker_cmd_file.write_text(
                    "RESUME" if now_playing else "PARK", encoding="utf-8",
                )
            self._prev_playing = now_playing

        active_entry = self.renderer.current_clip_entry()

        if active_entry and active_entry["frames"]:
            frame_count = len(active_entry["frames"])
            if direct_active:
                from .direct_control import display_phase_for_position
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
            write_status_file(status_path, self.direct_state, self.cruise_control, hud_active=hud_on)

    def _update_direct_overlay(self) -> None:
        from .direct_control import MIN_BPM, sample_waveform

        ds = self.direct_state
        position = 0
        start_phase = 0.0
        if self.tcode_sender is not None:
            position = self.tcode_sender.current_position()
            start_phase = self.tcode_sender.stroke_phase

        phase_per_second = ds.bpm / 60.0 / self.beats_per_loop if ds.bpm > 0 else 1.0
        # Show enough time so one full waveform cycle is visible at the slowest speed
        display_seconds = 60.0 * self.beats_per_loop / MIN_BPM

        self.set_direct_overlay(DirectOverlayData(
            speed=ds.speed,
            bpm=ds.bpm,
            amplitude=ds.amplitude,
            center=ds.center,
            waveform_points=sample_waveform(
                ds.shape, ds.amplitude, ds.center, 80,
                start_phase=start_phase,
                phase_range=phase_per_second * display_seconds,
            ),
            position=position,
            cruise_active=self.cruise_control.active if self.cruise_control else False,
            phase_per_second=phase_per_second,
            display_seconds=display_seconds,
        ))
