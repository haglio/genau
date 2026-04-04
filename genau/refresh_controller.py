from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .runtime_support import consume_command_file
from .engine import update_engine
from .refresh_logic import display_index_for_phase, read_shared_state_snapshot
from .runtime_commands import apply_runtime_command, get_engine_estimated_bpm


@dataclass
class DirectOverlayData:
    speed: int
    bpm: float
    amplitude: int
    center: int
    waveform_points: list[float]
    position: int
    auto_active: bool
    phase_per_second: float = 1.0


class RobotHandRefreshController:
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
        auto_pilot=None,
        set_direct_overlay=None,
        present_scene=None,
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
        self.auto_pilot = auto_pilot
        self.set_direct_overlay = set_direct_overlay or (lambda _data: None)
        self.present_scene = present_scene or (lambda: None)
        self.window_visible = False

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

        if self.direct_state is not None:
            if self.auto_pilot is not None:
                from .auto_pilot import tick_auto_pilot
                tick_auto_pilot(self.direct_state, self.auto_pilot, now)
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

        if self.tcode_sender is not None and self.direct_state is not None and self.direct_state.playing:
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if self.direct_state is not None:
            self._update_direct_overlay()

        apply_runtime_command(
            self.consume_command(self.command_file, logger=self.logger),
            engine=self.engine,
            rh_paused=self.rh_paused,
            step_clip=self.selection.step,
        )

        active_entry = self.renderer.current_clip_entry()

        if active_entry and active_entry["frames"]:
            frame_count = len(active_entry["frames"])
            if self.direct_state is not None:
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

    def _update_direct_overlay(self) -> None:
        from .direct_control import sample_waveform

        ds = self.direct_state
        position = 0
        start_phase = 0.0
        if self.tcode_sender is not None:
            position = self.tcode_sender.current_position()
            start_phase = self.tcode_sender.stroke_phase

        # Sample 4 seconds of upcoming waveform
        phase_per_second = ds.bpm / 60.0 / self.beats_per_loop if ds.bpm > 0 else 1.0
        display_seconds = 4.0

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
            auto_active=self.auto_pilot.active if self.auto_pilot else False,
            phase_per_second=phase_per_second,
        ))
