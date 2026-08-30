from __future__ import annotations

import time
from pathlib import Path

from player_core.clip_scrub import ClipScrub, scrub_clip
from player_core.file_channel import consume_command_file

from .engine import update_engine
from .controls import GenauControls
from .device_handoff import DeviceHandoff
from .drive_readout import DriveReadout
from .refresh_logic import display_index_for_phase, read_shared_state_snapshot
from .runtime_commands import apply_runtime_command
from .status_writer import write_status_file

class GenauRefreshController:
    def __init__(
        self,
        *,
        controls: GenauControls,
        state,
        loader,
        notifier,
        renderer,
        selection,
        command_file: Path,
        paused_file: Path,
        beats_per_loop: float,
        bpm_smoothing: float,
        sync_strength: float,
        set_loading_text,
        logger,
        now_source=time.monotonic,
        consume_command=consume_command_file,
        read_paused_state=None,
        tcode_sender=None,
        broker_cmd_file: Path | None = None,
        drive_file: Path | None = None,
        console_file: Path | None = None,
        set_console=None,
        present_scene=None,
        set_hud_mode=None,
        set_blank=None,
    ):
        self.controls = controls
        # The seven the tick itself reads, named here rather than reached for
        # through the controls on every line below.
        self.engine = controls.engine
        self.rh_paused = controls.rh_paused
        self.direct_state = controls.direct_state
        self.cruise_control = controls.cruise_control_state
        self.clip_advance = controls.clip_advance_state
        self.hud_state = controls.hud_state
        self.display_state = controls.display_state
        self.state = state
        self.loader = loader
        self.notifier = notifier
        self.renderer = renderer
        self.selection = selection
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
        self.tcode_sender = tcode_sender
        self.handoff = DeviceHandoff(
            playing=self.direct_state.playing,
            tcode_sender=tcode_sender,
            broker_cmd_file=broker_cmd_file,
        )
        self.readout = DriveReadout(
            controls=controls,
            beats_per_loop=beats_per_loop,
            tcode_sender=tcode_sender,
            drive_file=drive_file,
            console_file=console_file,
            set_console=set_console,
            current_clip=lambda: renderer.current_clip_path,
        )
        self.present_scene = present_scene or (lambda: None)
        self.set_hud_mode = set_hud_mode or (lambda _active: None)
        self.set_blank = set_blank or (lambda _blank: None)
        self._prev_hud_active: bool = (
            self.hud_state["active"] if self.hud_state is not None else False
        )
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
            apply_runtime_command(cmd, self.controls)

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

        # Seen the same tick the command landed, because the drain above runs
        # first.
        self.handoff.watch(self.direct_state.playing)

        if self.tcode_sender is not None and direct_active and self.direct_state.playing:
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if direct_active:
            self.readout.update(now)
        else:
            self.readout.blank()

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

