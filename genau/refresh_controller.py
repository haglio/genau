from __future__ import annotations

import time
from pathlib import Path

from player_core.clip_scrub import ClipScrub, scrub_clip
from player_core.cruise_control import tick_cruise_control
from player_core.direct_control import POSITION_MAX
from player_core.file_channel import consume_command_file

from .engine import update_engine
from .clip_advance import tick_clip_advance
from .config import GENAU_STATUS_FILENAME
from .controls import GenauControls
from .device_handoff import DeviceHandoff
from .drive_readout import DriveReadout
from .tick_failures import TickFailures
from .refresh_logic import Beat, display_index_for_phase, read_shared_state_snapshot
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
        status_file: Path | None = None,
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
        self.paused = controls.paused
        self.direct_state = controls.direct_state
        self.cruise_control = controls.cruise_control_state
        self.clip_advance = controls.clip_advance_state
        self.hud = controls.hud
        self.display = controls.display
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
        self.failures = TickFailures(logger)
        self.now_source = now_source
        self.consume_command = consume_command
        self.read_paused_state = read_paused_state or (lambda _path, logger=None: False)
        self.tcode_sender = tcode_sender
        # Beside the command file when nobody named one: standalone that is our
        # own state dir, and under an orchestrator that has not been told to
        # name it, it is wherever the orchestrator put the command channel --
        # which is where every version of Fun Time so far has looked.
        self.status_file = status_file or command_file.parent / GENAU_STATUS_FILENAME
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
        # Which half of the clip is showing, and what is known about the end
        # the stroke is at — see :meth:`_scrub_the_clip`.
        self._scrub = ClipScrub()

    def refresh(self) -> None:
        try:
            self._refresh_once()
        except Exception as exc:
            # Said once per kind rather than every frame: the loop calls this
            # again immediately, so a persistent fault would otherwise fill the
            # state directory the IPC files live in.
            self.failures.failed(exc)
            return
        self.failures.worked()

    def _refresh_once(self) -> None:
        """One turn of the loop, in the order the order matters.

        The drain runs first, before anything below reads the state a command
        moves and before this tick's stroke goes out; the arbitration decides who
        is driving before the engine is told anything; the frame is chosen after
        the engine has moved and shown before the scene is presented; and the
        status file goes out last, saying what the tick just did.
        """
        now = self.now_source()
        self._adopt_whatever_finished_decoding()
        self._drain_commands()

        beat = self._who_is_driving(now)

        # Said every tick and heard once: the notifier drops a repeat.  The
        # clip that goes with it is the clip selection's to announce, and it
        # already has by the time the first tick runs.
        self.notifier.notify_visible(True)

        update_engine(
            self.engine,
            now=now,
            auto_active=beat.auto_active,
            raw_bpm=beat.raw_bpm,
            sync_pulse_id=beat.sync_pulse_id,
            beats_per_loop=self.beats_per_loop,
            bpm_smoothing=self.bpm_smoothing,
            sync_strength=self.sync_strength,
            paused=beat.paused,
        )

        # Seen the same tick the command landed, because the drain above runs
        # first.
        self.handoff.watch(self.direct_state.playing)

        if self.tcode_sender is not None and beat.direct_active and self.direct_state.playing:
            self.tcode_sender.maybe_send(self.engine.phase, now)

        if beat.direct_active:
            self.readout.update(now)
        else:
            self.readout.blank()

        self._follow_the_window_flags()
        self._show_the_frame(beat)

        pending = self.selection.pending_clip_name
        self.set_loading_text(f"Loading {pending}" if pending else None)

        self.selection.request_nearby_prefetch()
        self.present_scene()
        self._publish_status()

    def _adopt_whatever_finished_decoding(self) -> None:
        self.loader.adopt_loaded_clip_if_ready()
        self.loader.adopt_prefetch_if_ready()
        self.selection.adopt_pending_clip()

    def _drain_commands(self) -> None:
        for cmd in self.consume_command(self.command_file, logger=self.logger):
            apply_runtime_command(cmd, self.controls)

    def _who_is_driving(self, now: float) -> Beat:
        """Genau's own hand, or the broker — and what the engine is told either way."""
        shared = read_shared_state_snapshot(self.state)
        if shared.auto_active:
            self.paused.on = self.read_paused_state(
                self.paused_file, logger=self.logger)
            return Beat(
                direct_active=False,
                auto_active=shared.auto_active,
                raw_bpm=shared.raw_bpm,
                paused=self.paused.on,
                sync_pulse_id=shared.sync_pulse_id,
            )
        self._tick_the_hand(now)
        return Beat(
            direct_active=True,
            auto_active=self.direct_state.playing,
            raw_bpm=self.direct_state.bpm,
            paused=not self.direct_state.playing,
            sync_pulse_id=0,
        )

    def _tick_the_hand(self, now: float) -> None:
        """The two things that move the hand on their own: the cruise stack
        varying it, and the clip advance letting the picture move on."""
        if self.cruise_control is not None:
            # The phase is only read on the tick that draws the waves: they
            # all start where the stroke already is, so taking over cannot
            # be felt.
            tick_cruise_control(
                self.direct_state, self.cruise_control, now,
                phase=(self.tcode_sender.stroke_phase
                       if self.tcode_sender is not None else 0.0),
            )
        if self.clip_advance is not None:
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

    def _follow_the_window_flags(self) -> None:
        """The two things an orchestrator flips that the window has to be told."""
        if self.hud is not None and self.hud.moved():
            self.set_hud_mode(self.hud.on)

        # Paint black only while an orchestrator has told us we aren't the active
        # display.  Deliberately NOT keyed off playback: a paused hand is normal
        # (standalone boots paused, and OmniPause freezes it mid-session), and
        # blanking on that hides the clip the user is looking at.
        display_active = self.display.on if self.display is not None else True
        self.set_blank(not display_active)

    def _show_the_frame(self, beat: Beat) -> None:
        """Which frame of the decoded clip to put up.

        Driving its own hand, the frame is the picture of where the device is;
        under the broker it is where the engine's phase has reached.
        """
        active_entry = self.renderer.current_clip_entry()
        if not (active_entry and active_entry["frames"]):
            return
        frame_count = len(active_entry["frames"])
        display_phase = (
            self._scrub_the_clip(frame_count) if beat.direct_active
            else self.engine.phase
        )
        self.renderer.display_frame(display_index_for_phase(
            phase=display_phase,
            frame_count=frame_count,
            auto_active=beat.auto_active,
            current_frame_index=self.renderer.current_frame_index,
        ))

    def _publish_status(self) -> None:
        if self.cruise_control is None:
            return
        hud_on = self.hud.on if self.hud is not None else False
        write_status_file(
            self.status_file,
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
        if self.tcode_sender is None:
            return self.engine.phase
        return scrub_clip(
            self._scrub,
            self.tcode_sender.current_position() / POSITION_MAX,
            frame_count,
        )

