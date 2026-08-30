from __future__ import annotations

import random
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from player_core.cruise_control import CruiseControlState
from genau.clip_advance import ClipAdvanceState
from genau.controls import GenauControls
from player_core.direct_control import DirectControlState
from genau.engine import PlaybackEngine
from genau.flags import Flag
from genau.refresh_controller import GenauRefreshController
from genau.state import SharedState


class FakeLoader:
    def __init__(self, *, loading: bool = False):
        self.load_state = type("LoadState", (), {"loading": loading})()
        self.loaded_adopt_calls = 0
        self.prefetch_adopt_calls = 0

    def adopt_loaded_clip_if_ready(self) -> None:
        self.loaded_adopt_calls += 1

    def adopt_prefetch_if_ready(self) -> None:
        self.prefetch_adopt_calls += 1


class FakeNotifier:
    def __init__(self):
        self.visible_updates: list[bool] = []

    def notify_visible(self, is_visible: bool) -> None:
        self.visible_updates.append(is_visible)


class FakeRenderer:
    def __init__(self, *, path: Path | None = None, entry=None, current_frame_index: int | None = None):
        self.current_clip_path = path
        self._entry = entry
        self.current_frame_index = current_frame_index
        self.display_calls: list[int] = []

    def current_clip_entry(self):
        return self._entry

    def show_frame_at(self, index: int) -> None:
        self.display_calls.append(index)


class FakeSelection:
    def __init__(self, *, current_number: int = 2, count: int = 5, pending_clip_name: str | None = None):
        self.current_number = current_number
        self.count = count
        self.step_calls: list[int] = []
        self.discard_calls = 0
        self.prefetch_calls = 0
        self.adopt_calls = 0
        self.pending_clip_name = pending_clip_name

    def step(self, delta: int) -> None:
        self.step_calls.append(delta)

    def condemn_current(self) -> bool:
        self.discard_calls += 1
        return True

    def adopt_pending_clip(self) -> bool:
        self.adopt_calls += 1
        return False

    def request_nearby_prefetch(self) -> None:
        self.prefetch_calls += 1


class FakeTCodeSender:
    def __init__(self):
        self.sends: list[tuple[float, float]] = []
        self.take_overs = 0
        self.rests = 0
        self.hand_overs = 0
        self.let_go_position: int | None = None
        self.closed = False
        self._position = 5000
        self._stroke_phase = 0.0

    def maybe_send(self, phase: float, now: float) -> None:
        self.sends.append((phase, now))
        self._stroke_phase = phase

    def take_over(self) -> None:
        self.take_overs += 1
        self.let_go_position = None

    def rest_at_bottom(self) -> None:
        self.rests += 1
        self._stroke_phase = 0.0

    def set_stroke_phase(self, phase: float) -> None:
        self._stroke_phase = phase

    def hand_over(self) -> None:
        self.hand_overs += 1
        self.let_go_position = self._position
        self.rest_at_bottom()

    def current_position(self) -> int:
        return self._position

    @property
    def stroke_phase(self) -> float:
        return self._stroke_phase

    def close(self) -> None:
        self.closed = True


def _build_controller(
    *,
    state: SharedState | None = None,
    loading: bool = False,
    path: str | None = "demo.mp4",
    entry=None,
    current_frame_index: int | None = None,
    command: str | None = None,
    commands: list[str] | None = None,
    paused_state: bool = False,
    pending_clip_name: str | None = None,
    # The state the app itself opens on: not playing, mid speed.  Genau always
    # has one, so a test that does not care about it still gets it.
    direct_state: DirectControlState | None = None,
    tcode_sender: FakeTCodeSender | None = None,
    cruise_control: CruiseControlState | None = None,
    clip_advance: ClipAdvanceState | None = None,
    broker_cmd_file: Path | None = None,
    hud: Flag | None = None,
    set_hud_mode=None,
    display: Flag | None = None,
    command_file: Path | None = None,
    status_file: Path | None = None,
):
    loading_texts: list[str | None] = []
    consoles: list = []
    present_calls: list[int] = []
    hud_mode_calls: list[bool] = []
    blank_calls: list[bool] = []

    loader = FakeLoader(loading=loading)
    notifier = FakeNotifier()
    renderer = FakeRenderer(
        path=Path(path) if path is not None else None,
        entry=entry,
        current_frame_index=current_frame_index,
    )
    selection = FakeSelection(pending_clip_name=pending_clip_name)
    engine = PlaybackEngine(phase=0.25, last_tick=5.0)
    logger = MagicMock()
    controls = GenauControls(
        engine=engine,
        paused=Flag(),
        step_clip=selection.step,
        condemn_clip=selection.condemn_current,
        direct_state=direct_state if direct_state is not None else DirectControlState(),
        cruise_control_state=cruise_control,
        set_stroke_phase=(
            tcode_sender.set_stroke_phase if tcode_sender is not None else None
        ),
        clip_advance_state=clip_advance,
        hud=hud,
        display=display,
        # A Genau with no chip to draw still answers SET_VOLUME: the level is the
        # orchestrator's, and refusing it would put an unhandled verb on the log
        # every time the room's volume moved.
        set_volume=lambda _level, _muted: None,
    )
    controller = GenauRefreshController(
        controls=controls,
        state=state or SharedState(),
        loader=loader,
        notifier=notifier,
        renderer=renderer,
        selection=selection,
        # Absolute scratch paths: the controller writes genau_status.txt next
        # to the command file, so a relative path would pollute pytest's CWD.
        command_file=command_file or (
            Path(tempfile.mkdtemp(prefix="genau-refresh-")) / "command.txt"),
        status_file=status_file,
        paused_file=Path("paused.txt"),
        beats_per_loop=4.0,
        bpm_smoothing=0.5,
        sync_strength=0.5,
        set_loading_text=loading_texts.append,
        logger=logger,
        now_source=lambda: 5.0,
        consume_command=lambda _path, logger=None: (commands if commands is not None else ([command] if command else [])),
        read_paused_state=lambda _path, logger=None: paused_state,
        tcode_sender=tcode_sender,
        broker_cmd_file=broker_cmd_file,
        set_console=consoles.append,
        present_scene=lambda: present_calls.append(1),
        set_hud_mode=set_hud_mode or hud_mode_calls.append,
        set_blank=blank_calls.append,
    )
    return {
        "controller": controller,
        "loader": loader,
        "notifier": notifier,
        "renderer": renderer,
        "selection": selection,
        "engine": engine,
        "logger": logger,
        "loading_texts": loading_texts,
        "consoles": consoles,
        "present_calls": present_calls,
        "hud_mode_calls": hud_mode_calls,
        "blank_calls": blank_calls,
    }


def test_refresh_displays_active_frame():
    state = SharedState(auto_active=True, raw_bpm=120.0)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry)

    built["controller"].refresh()

    assert built["loader"].loaded_adopt_calls == 1
    assert built["loader"].prefetch_adopt_calls == 1
    assert built["renderer"].display_calls == [5]
    assert built["selection"].prefetch_calls == 1


def test_refresh_skips_display_when_no_frames_are_ready():
    built = _build_controller(loading=True, entry=None)

    built["controller"].refresh()

    assert built["renderer"].display_calls == []
    assert built["selection"].prefetch_calls == 1


def test_refresh_applies_runtime_commands_through_selection_step():
    built = _build_controller(command="NEXT", entry=None)

    built["controller"].refresh()

    assert built["selection"].step_calls == [1]


def test_refresh_reads_paused_state_file_each_tick():
    """The paused file is the broker's word, so it is read on the broker's path."""
    entry = {"frames": [object() for _ in range(4)]}
    built = _build_controller(
        state=SharedState(auto_active=True), entry=entry, paused_state=True)

    built["controller"].refresh()

    assert built["controller"].paused.on is True


def test_refresh_reports_exceptions():
    built = _build_controller(entry=None)
    built["renderer"].current_clip_entry = MagicMock(side_effect=RuntimeError("kaboom"))

    built["controller"].refresh()

    said = built["logger"].error.call_args
    assert said[0][0] == "refresh failed"
    assert isinstance(said[1]["exc_info"], RuntimeError)


def test_a_fault_that_repeats_every_frame_is_said_once():
    """The loop calls refresh again immediately at up to 120fps, so a
    persistent fault used to write thousands of tracebacks a second into the
    state directory the three other IPC files live in."""
    built = _build_controller(entry=None)
    built["renderer"].current_clip_entry = MagicMock(side_effect=RuntimeError("kaboom"))

    for _ in range(100):
        built["controller"].refresh()

    assert built["logger"].error.call_count == 1
    assert built["logger"].debug.call_count == 99


def test_refresh_sets_loading_text_when_pending_clip():
    entry = {"frames": [object() for _ in range(4)]}
    built = _build_controller(entry=entry, pending_clip_name="next.mp4")

    built["controller"].refresh()

    assert built["loading_texts"][-1] == "Loading next.mp4"


def test_refresh_clears_loading_text_when_no_pending_clip():
    entry = {"frames": [object() for _ in range(4)]}
    built = _build_controller(entry=entry, pending_clip_name=None)

    built["controller"].refresh()

    assert built["loading_texts"][-1] is None


def test_refresh_calls_adopt_pending_clip():
    entry = {"frames": [object() for _ in range(4)]}
    built = _build_controller(entry=entry)

    built["controller"].refresh()

    assert built["selection"].adopt_calls == 1


def test_direct_mode_playing_advances_phase():
    dc = DirectControlState(playing=True, bpm=120.0)
    entry = {"frames": [object() for _ in range(8)]}
    # SharedState has auto_active=False, but direct mode should override
    built = _build_controller(entry=entry, direct_state=dc)
    # Advance the clock so dt > 0 (engine.last_tick starts at 5.0)
    built["controller"].now_source = lambda: 5.05

    built["controller"].refresh()

    # Engine should have advanced phase since direct_state.playing=True
    assert built["engine"].phase != 0.25  # initial was 0.25


def test_direct_mode_not_playing_freezes_phase():
    dc = DirectControlState(playing=False, bpm=120.0)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc)

    built["controller"].refresh()

    assert built["engine"].phase == 0.25  # unchanged


def test_direct_mode_calls_tcode_sender():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert len(tcode.sends) == 1
    phase, now = tcode.sends[0]
    assert now == 5.0


def test_direct_mode_paused_does_not_send_tcode():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert tcode.sends == []


def test_direct_mode_publishes_the_drive_readout():
    dc = DirectControlState(playing=True, bpm=120.0, amplitude=70, intended_center=60)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert len(built["consoles"]) == 1
    hud = built["consoles"][0].drive
    assert (hud.amplitude, hud.center, hud.speed) == (70, 60, 50)
    assert hud.shape == "sine"  # named on the panel, not only drawn
    assert len(hud.waveform) == 80


def test_direct_mode_calls_present_scene():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert len(built["present_calls"]) == 1


def test_pause_command_stops_direct_mode_playback():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="PAUSE")

    built["controller"].refresh()

    assert dc.playing is False


def test_pause_command_writes_park_to_broker_cmd_file(tmp_path):
    broker_cmd = tmp_path / "broker_cmd.txt"
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        command="PAUSE", broker_cmd_file=broker_cmd,
    )

    built["controller"].refresh()

    assert broker_cmd.read_text(encoding="utf-8") == "PARK"


def test_pause_without_broker_cmd_file_does_not_error():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="PAUSE")

    built["controller"].refresh()  # No broker_cmd_file — should not raise


def test_resume_command_writes_resume_to_broker_cmd_file(tmp_path):
    broker_cmd = tmp_path / "broker_cmd.txt"
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        command="RESUME", broker_cmd_file=broker_cmd,
    )

    built["controller"].refresh()

    assert broker_cmd.read_text(encoding="utf-8") == "RESUME"


def test_pause_between_refreshes_writes_park(tmp_path):
    """Pause via lifecycle controller (not command file) is detected on next refresh."""
    broker_cmd = tmp_path / "broker_cmd.txt"
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        broker_cmd_file=broker_cmd,
    )

    # First refresh — playing, no transition
    built["controller"].refresh()
    assert not broker_cmd.exists()

    # Pause happens outside the refresh loop (e.g. space key)
    dc.playing = False

    # Next refresh should detect the transition
    built["controller"].refresh()
    assert broker_cmd.read_text(encoding="utf-8") == "PARK"


def test_resume_between_refreshes_writes_resume(tmp_path):
    """Resume via lifecycle controller is detected on next refresh."""
    broker_cmd = tmp_path / "broker_cmd.txt"
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        broker_cmd_file=broker_cmd,
    )

    # First refresh — paused, no transition
    built["controller"].refresh()
    assert not broker_cmd.exists()

    # Resume happens outside the refresh loop
    dc.playing = True

    # Next refresh should detect the transition
    built["controller"].refresh()
    assert broker_cmd.read_text(encoding="utf-8") == "RESUME"


def test_losing_the_device_walks_it_down_and_rests_the_stroke():
    """The readout published through a funscript's turn (or any pause) samples
    forward from the sender's stroke phase — rested at the swing's foot the
    moment playback stops, so what Nau draws waiting behind the seam is the
    stroke that will actually resume, rising out of the park."""
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="PAUSE")

    built["controller"].refresh()

    assert tcode.rests == 1


def test_staying_paused_hands_over_only_once():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="PAUSE")

    built["controller"].refresh()
    built["controller"].refresh()

    assert tcode.rests == 1


def test_resume_command_starts_direct_mode_playback():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="RESUME")

    built["controller"].refresh()

    assert dc.playing is True


def test_speed_up_command_via_refresh():
    dc = DirectControlState(playing=True, bpm=120.0, speed=50)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode, command="SPEED_UP")

    built["controller"].refresh()

    assert dc.speed == 55


def test_toggle_cruise_command_via_refresh():
    dc = DirectControlState(playing=True, bpm=120.0)
    auto = CruiseControlState(active=False)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode, cruise_control=auto, command="TOGGLE_CRUISE"
    )

    built["controller"].refresh()

    assert auto.active is True


def test_toggle_lock_command_via_refresh():
    dc = DirectControlState(playing=True, bpm=120.0)
    aa = ClipAdvanceState(locked=True)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=FakeTCodeSender(),
        clip_advance=aa, command="TOGGLE_LOCK",
    )

    built["controller"].refresh()

    assert aa.locked is False


def test_cruise_control_ticks_during_refresh():
    dc = DirectControlState(playing=True, bpm=120.0, speed=50)
    auto = CruiseControlState(active=True, rng=random.Random(42))
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode, cruise_control=auto
    )
    # Advance clock enough that auto pilot actually triggers changes
    tick = 0.0
    for _ in range(200):
        tick += 0.1
        built["controller"].now_source = lambda t=tick: 5.0 + t
        built["controller"].refresh()
    # Auto pilot should have changed something
    assert dc.speed != 50 or dc.amplitude != 100 or dc.center != 50


def _run_clip_advance(*, playing: bool, seconds: float = 15.0, locked: bool = False):
    dc = DirectControlState(playing=playing, bpm=120.0)
    aa = ClipAdvanceState(locked=locked, interval=10)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=FakeTCodeSender(), clip_advance=aa
    )
    tick = 0.0
    for _ in range(int(seconds / 0.1)):
        tick += 0.1
        built["controller"].now_source = lambda t=tick: 5.0 + t
        built["controller"].refresh()
    return built["selection"].step_calls


def test_an_unlocked_genau_advances_its_clip_during_refresh():
    steps = _run_clip_advance(playing=True)
    assert len(steps) >= 1
    assert all(c == 1 for c in steps)


def test_a_locked_genau_stays_on_its_clip():
    assert _run_clip_advance(playing=True, seconds=60.0, locked=True) == []


def test_the_clip_is_held_while_the_room_is_paused():
    """OmniPause reaches Genau as PAUSE, which clears direct_state.playing.

    The advance has to read that: a paused room that keeps swapping clips
    leaves the user looking at something they never chose to move to.
    """
    assert _run_clip_advance(playing=False, seconds=60.0) == []


def test_broker_auto_uses_broker_bpm_for_phase():
    """When broker signals auto, direct mode should use broker BPM for phase."""
    dc = DirectControlState(playing=False, bpm=60.0)
    state = SharedState(auto_active=True, raw_bpm=120.0)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry, direct_state=dc)
    built["controller"].now_source = lambda: 5.05

    built["controller"].refresh()

    # Phase should have advanced using broker BPM (120), not direct_state BPM (60)
    # With 120 BPM, beats_per_loop=4, loop_duration = (60/120)*4 = 2s
    # dt=0.05, phase advance = 0.05/2 = 0.025 → 0.25 + 0.025 = 0.275
    assert abs(built["engine"].phase - 0.275) < 0.001


def test_broker_auto_does_not_send_tcode():
    """When broker signals auto, T-Code should not be sent even if direct_state.playing."""
    dc = DirectControlState(playing=True, bpm=120.0)
    state = SharedState(auto_active=True, raw_bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert tcode.sends == []


def test_broker_auto_uses_linear_display_phase():
    """When broker signals auto, display should use engine phase directly, not waveform."""
    dc = DirectControlState(playing=False, bpm=60.0)
    state = SharedState(auto_active=True, raw_bpm=120.0)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry, direct_state=dc)

    built["controller"].refresh()

    # Engine phase is 0.25, frame_count=8
    # Linear: logical_index = int(0.25 * 8) = 2, display = 7 - 2 = 5
    assert built["renderer"].display_calls == [5]


def test_broker_auto_does_not_tick_cruise_control():
    """When broker signals auto, cruise control should not modify direct state."""
    dc = DirectControlState(playing=True, bpm=120.0, speed=50)
    cruise = CruiseControlState(active=True, rng=random.Random(42))
    state = SharedState(auto_active=True, raw_bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        state=state, entry=entry, direct_state=dc, tcode_sender=tcode, cruise_control=cruise,
    )
    tick = 0.0
    for _ in range(200):
        tick += 0.1
        built["controller"].now_source = lambda t=tick: 5.0 + t
        built["controller"].refresh()

    assert dc.speed == 50 and dc.amplitude == 100 and dc.center == 50


def test_broker_auto_respects_sync_pulses():
    """When broker signals auto, sync pulses should pull phase toward zero."""
    dc = DirectControlState(playing=False, bpm=60.0)
    state = SharedState(auto_active=True, raw_bpm=120.0, sync_pulse_id=1)
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry, direct_state=dc)

    built["controller"].refresh()

    # Engine starts at phase 0.25, sync_strength=0.5
    # Sync correction: error = -0.25 (since 0.25 <= 0.5), phase += -0.25 * 0.5 = -0.125
    # New phase = 0.25 - 0.125 = 0.125
    assert abs(built["engine"].phase - 0.125) < 0.001


def test_broker_auto_cleared_resumes_direct_control():
    """When broker auto clears, direct control resumes: T-Code sends, overlay updates."""
    dc = DirectControlState(playing=True, bpm=120.0)
    state = SharedState(auto_active=False, raw_bpm=0.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(state=state, entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert len(tcode.sends) == 1
    assert len(built["consoles"]) == 1


def test_multiline_commands_all_applied():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = Flag()
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["RESUME", "HUD_ON"],
        hud=hud,
    )

    built["controller"].refresh()

    assert dc.playing is True
    assert hud.on is True


def test_paused_alone_does_not_blank():
    """Standalone Genau boots paused and is driven from the keyboard — a paused
    hand still shows its clip. Only an orchestrator saying "you aren't the
    display" (DISPLAY_OFF) blanks it."""
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert built["blank_calls"] == [False]


def test_playing_does_not_blank():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert built["blank_calls"] == [False]


def test_inactive_display_blanks():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        display=Flag(),
    )

    built["controller"].refresh()

    assert built["blank_calls"] == [True]


def test_display_off_command_blanks_within_the_same_refresh():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    display = Flag(on=True)
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        command="DISPLAY_OFF", display=display,
    )

    built["controller"].refresh()

    assert display.on is False
    assert built["blank_calls"] == [True]


def test_hud_on_command_calls_set_hud_mode():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = Flag()
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["HUD_ON"],
        hud=hud,
    )

    built["controller"].refresh()

    assert built["hud_mode_calls"] == [True]


def test_hud_off_command_calls_set_hud_mode_false():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = Flag(on=True)
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["HUD_OFF"],
        hud=hud,
    )

    built["controller"].refresh()

    assert built["hud_mode_calls"] == [False]


def test_the_hud_is_published_in_the_status_file(tmp_path):
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = Flag(on=True)
    cruise = CruiseControlState()
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        cruise_control=cruise, hud=hud,
        command_file=tmp_path / "genau_cmd.txt",
    )

    built["controller"].refresh()

    status_path = tmp_path / "genau_status.txt"
    assert status_path.exists()
    text = status_path.read_text(encoding="utf-8")
    assert "hud=1" in text


class TestWhereTheStatusFileGoes:
    """Fun Time's dashboard, dispatch loop and sequencer all read this file, so
    where it lands is a contract rather than a detail."""

    @staticmethod
    def _ticked(tmp_path, **over):
        built = _build_controller(
            entry={"frames": [object() for _ in range(4)]},
            direct_state=DirectControlState(playing=True, bpm=120.0),
            tcode_sender=FakeTCodeSender(),
            cruise_control=CruiseControlState(),
            **over,
        )
        built["controller"].refresh()
        return built["controller"]

    def test_it_goes_beside_the_command_file_when_nobody_names_it(self, tmp_path):
        """Which is where every version of Fun Time so far has looked."""
        self._ticked(tmp_path, command_file=tmp_path / "genau_cmd.txt")

        assert (tmp_path / "genau_status.txt").exists()

    def test_a_launcher_that_names_one_gets_that_one(self, tmp_path):
        named = tmp_path / "elsewhere" / "genau_status.txt"

        self._ticked(tmp_path, command_file=tmp_path / "genau_cmd.txt",
                     status_file=named)

        assert named.exists()
        assert not (tmp_path / "genau_status.txt").exists()

    def test_it_is_named_once_rather_than_rebuilt_every_tick(self, tmp_path):
        """Resolved once, so nothing can move it mid-session."""
        controller = self._ticked(tmp_path, command_file=tmp_path / "genau_cmd.txt")

        assert controller.status_file == tmp_path / "genau_status.txt"


def test_the_frame_shown_is_where_the_device_is():
    # The clip is the picture of the device: half way up the axis is half way
    # through the half of the clip that is showing. Eight frames, so the front
    # half is the last four of them and 5000 of 9999 lands in the middle of it.
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    tcode._position = 5000
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)

    built["controller"].refresh()

    assert built["renderer"].display_calls[-1] == 5


def test_turning_at_the_top_puts_the_other_half_of_the_clip_on_the_way_down():
    # The one place the halves may be swapped is an end, where they show the
    # same frame — so the way down is the back half, and the height that showed
    # frame 5 climbing shows its opposite number in the loop coming back.
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    tcode._position = 5000
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)
    controller = built["controller"]

    controller.refresh()
    tcode._position = 9999           # at B
    controller.refresh()
    tcode._position = 9000           # and turning back
    controller.refresh()
    tcode._position = 5000
    controller.refresh()

    assert built["renderer"].display_calls[-1] == 2


def test_a_stroke_that_never_reaches_an_end_keeps_the_half_it_is_in():
    # Working the middle of the axis shows the middle of the one half, up and
    # back down it, rather than rolling on into the other.
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    tcode._position = 3000
    entry = {"frames": [object() for _ in range(8)]}
    built = _build_controller(entry=entry, direct_state=dc, tcode_sender=tcode)
    controller = built["controller"]

    for position in (3000, 6000, 8000, 6000, 3000, 6000):
        tcode._position = position
        controller.refresh()

    assert built["controller"]._scrub.back_half is False
    assert built["renderer"].display_calls[-1] == 5


def test_the_controller_cannot_be_built_without_a_direct_state():
    """Genau has one playback mode, and the constructor says so.

    A passive mode used to exist for a state the app never builds; the guards
    that read it were decided at build time. The parameter is required so the
    second mode cannot come back by omitting an argument.
    """
    import pytest

    with pytest.raises(TypeError):
        GenauRefreshController(
            state=SharedState(),
            loader=FakeLoader(),
            notifier=FakeNotifier(),
            renderer=FakeRenderer(),
            selection=FakeSelection(),
            engine=PlaybackEngine(phase=0.0, last_tick=0.0),
            paused=Flag(),
            command_file=Path("command.txt"),
            paused_file=Path("paused.txt"),
            beats_per_loop=4.0,
            bpm_smoothing=0.5,
            sync_strength=0.5,
            set_loading_text=lambda _text: None,
            logger=MagicMock(),
        )


class TestTheOrderTheTickDoesThingsIn:
    """The tick's sequence is load-bearing and was held together by comments.

    Each of these is a reordering that leaves every unit test green, because
    every part is correct and only the order between them is wrong.  Read off
    the syntax tree, because most of them cannot be seen from outside a tick:
    two of the steps write files, one paints, and the rest move state that the
    next step reads.
    """

    @staticmethod
    def _steps() -> list[str]:
        """The calls `_refresh_once` makes, in source order."""
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1]
                  / "genau" / "refresh_controller.py").read_text(encoding="utf-8")
        body = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef) and n.name == "_refresh_once")
        calls = [n for n in ast.walk(body) if isinstance(n, ast.Call)]
        # ast.walk is breadth-first, so a call inside a branch would otherwise
        # sort after one written below it.
        calls.sort(key=lambda n: (n.lineno, n.col_offset))
        return [ast.unparse(n.func) for n in calls]

    def _before(self, first: str, second: str) -> None:
        steps = self._steps()
        assert first in steps, f"{first} is not in the tick"
        assert second in steps, f"{second} is not in the tick"
        assert steps.index(first) < steps.index(second), f"{first} must precede {second}"

    def test_commands_are_drained_before_anything_reads_what_they_moved(self):
        """A PAUSE that lands this tick has to be a falling edge this tick, not
        next: drained late, the stroke goes out once more after the hand stopped
        and the broker is told a tick behind."""
        self._before("self._drain_commands", "self._who_is_driving")
        self._before("self._drain_commands", "self.handoff.watch")
        self._before("self._drain_commands", "self.tcode_sender.maybe_send")

    def test_the_clip_that_finished_decoding_is_adopted_before_it_is_drawn(self):
        """Adopted after, a clip is one tick late on screen every time one
        loads, and the advance times its interval against the old one."""
        self._before("self._adopt_whatever_finished_decoding", "self._show_the_frame")

    def test_who_is_driving_is_settled_before_the_engine_is_told_anything(self):
        self._before("self._who_is_driving", "update_engine")

    def test_the_engine_moves_before_the_frame_is_chosen_from_its_phase(self):
        """Chosen first, every frame is the one the phase had last tick."""
        self._before("update_engine", "self._show_the_frame")

    def test_the_frame_is_shown_before_the_scene_is_presented(self):
        """Presented first and the window shows the previous frame for a whole
        turn, which is a visible stutter at 120fps."""
        self._before("self._show_the_frame", "self.present_scene")

    def test_the_status_file_goes_out_last_saying_what_this_tick_did(self):
        steps = self._steps()

        assert steps[-1] == "self._publish_status"
