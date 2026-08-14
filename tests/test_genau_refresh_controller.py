from __future__ import annotations

import random
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from player_core.cruise_control import CruiseControlState
from genau.clip_advance import ClipAdvanceState
from player_core.direct_control import DirectControlState
from genau.engine import PlaybackEngine
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
    def __init__(self, *, window_visible: bool = False):
        self.window_visible = window_visible
        self.calls: list[dict] = []

    def sync_window_visibility(self, **kwargs):
        self.calls.append(kwargs)
        return self.window_visible


class FakeRenderer:
    def __init__(self, *, path: Path | None = None, entry=None, current_frame_index: int | None = None):
        self.current_clip_path = path
        self._entry = entry
        self.current_frame_index = current_frame_index
        self.display_calls: list[int] = []

    def current_clip_entry(self):
        return self._entry

    def display_frame(self, index: int) -> None:
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

    def discard_current(self) -> bool:
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
        self.closed = False
        self._position = 5000
        self._stroke_phase = 0.0

    def maybe_send(self, phase: float, now: float) -> None:
        self.sends.append((phase, now))
        self._stroke_phase = phase

    def take_over(self) -> None:
        self.take_overs += 1

    def rest_at_bottom(self) -> None:
        self.rests += 1
        self._stroke_phase = 0.0

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
    direct_state: DirectControlState | None = None,
    tcode_sender: FakeTCodeSender | None = None,
    cruise_control: CruiseControlState | None = None,
    clip_advance: ClipAdvanceState | None = None,
    broker_cmd_file: Path | None = None,
    hud_state: dict | None = None,
    set_hud_mode=None,
    display_state: dict | None = None,
):
    loading_texts: list[str | None] = []
    show_window_calls: list[str] = []
    hide_window_calls: list[str] = []
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
    controller = GenauRefreshController(
        state=state or SharedState(),
        loader=loader,
        notifier=notifier,
        renderer=renderer,
        selection=selection,
        engine=engine,
        rh_paused={"value": False},
        # Absolute scratch paths: the controller writes genau_status.txt next
        # to the command file, so a relative path would pollute pytest's CWD.
        command_file=Path(tempfile.mkdtemp(prefix="genau-refresh-")) / "command.txt",
        paused_file=Path("paused.txt"),
        beats_per_loop=4.0,
        bpm_smoothing=0.5,
        sync_strength=0.5,
        show_window=lambda: show_window_calls.append("show"),
        hide_window=lambda: hide_window_calls.append("hide"),
        set_loading_text=loading_texts.append,
        logger=logger,
        log_name="genau_listener.log",
        now_source=lambda: 5.0,
        consume_command=lambda _path, logger=None: (commands if commands is not None else ([command] if command else [])),
        read_paused_state=lambda _path, logger=None: paused_state,
        direct_state=direct_state,
        tcode_sender=tcode_sender,
        cruise_control=cruise_control,
        clip_advance=clip_advance,
        broker_cmd_file=broker_cmd_file,
        set_console=consoles.append,
        present_scene=lambda: present_calls.append(1),
        hud_state=hud_state,
        set_hud_mode=set_hud_mode or hud_mode_calls.append,
        set_blank=blank_calls.append,
        display_state=display_state,
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
        "show_window_calls": show_window_calls,
        "hide_window_calls": hide_window_calls,
        "consoles": consoles,
        "present_calls": present_calls,
        "hud_mode_calls": hud_mode_calls,
        "blank_calls": blank_calls,
    }


def test_refresh_displays_active_frame():
    state = SharedState(
        auto_active=True,
        visible=True,
        raw_bpm=120.0,
        beats=4,
        stroke_name="pull",
        pattern_duration=1.5,
        last_msg="AUTO 1",
    )
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


def test_refresh_skips_prefetch_when_state_has_error():
    built = _build_controller(state=SharedState(error="boom"))

    built["controller"].refresh()

    assert built["selection"].prefetch_calls == 0


def test_refresh_applies_runtime_commands_through_selection_step():
    built = _build_controller(command="NEXT", entry=None)

    built["controller"].refresh()

    assert built["selection"].step_calls == [1]


def test_refresh_reads_paused_state_file_each_tick():
    entry = {"frames": [object() for _ in range(4)]}
    built = _build_controller(entry=entry, paused_state=True)

    built["controller"].refresh()

    assert built["controller"].rh_paused["value"] is True


def test_refresh_reports_exceptions():
    built = _build_controller(entry=None)
    built["renderer"].current_clip_entry = MagicMock(side_effect=RuntimeError("kaboom"))

    built["controller"].refresh()

    built["logger"].exception.assert_called_once_with("refresh failed")


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


def test_no_tcode_sender_in_passive_mode():
    entry = {"frames": [object() for _ in range(8)]}
    state = SharedState(auto_active=True, visible=True, raw_bpm=120.0)
    built = _build_controller(state=state, entry=entry, tcode_sender=None)

    # Should not raise
    built["controller"].refresh()


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


def test_passive_mode_does_not_call_present_scene():
    entry = {"frames": [object() for _ in range(8)]}
    state = SharedState(auto_active=True, visible=True, raw_bpm=120.0)
    built = _build_controller(state=state, entry=entry)

    built["controller"].refresh()

    assert len(built["present_calls"]) == 0


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


def test_losing_the_device_rests_the_stroke_at_its_bottom():
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


def test_staying_paused_rests_the_stroke_only_once():
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
    hud = {"active": False}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["RESUME", "HUD_ON"],
        hud_state=hud,
    )

    built["controller"].refresh()

    assert dc.playing is True
    assert hud["active"] is True


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
        display_state={"active": False},
    )

    built["controller"].refresh()

    assert built["blank_calls"] == [True]


def test_display_off_command_blanks_within_the_same_refresh():
    dc = DirectControlState(playing=False, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    display = {"active": True}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        command="DISPLAY_OFF", display_state=display,
    )

    built["controller"].refresh()

    assert display["active"] is False
    assert built["blank_calls"] == [True]


def test_hud_on_command_calls_set_hud_mode():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = {"active": False}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["HUD_ON"],
        hud_state=hud,
    )

    built["controller"].refresh()

    assert built["hud_mode_calls"] == [True]


def test_hud_off_command_calls_set_hud_mode_false():
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = {"active": True}
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        commands=["HUD_OFF"],
        hud_state=hud,
    )

    built["controller"].refresh()

    assert built["hud_mode_calls"] == [False]


def test_hud_state_included_in_status_file(tmp_path):
    dc = DirectControlState(playing=True, bpm=120.0)
    tcode = FakeTCodeSender()
    entry = {"frames": [object() for _ in range(8)]}
    hud = {"active": True}
    cruise = CruiseControlState()
    built = _build_controller(
        entry=entry, direct_state=dc, tcode_sender=tcode,
        cruise_control=cruise, hud_state=hud,
    )
    # Point the command file parent at tmp_path so status file lands there
    built["controller"].command_file = tmp_path / "genau_cmd.txt"

    built["controller"].refresh()

    status_path = tmp_path / "genau_status.txt"
    assert status_path.exists()
    text = status_path.read_text(encoding="utf-8")
    assert "hud=1" in text
