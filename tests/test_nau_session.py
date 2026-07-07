from __future__ import annotations

from pathlib import Path

from nau.funscript import Funscript
from nau.session import MAX_SPEED_RATE, MIN_SPEED_RATE, PlayerSession


class FakePlayer:
    """Stand-in for the mpv-backed player: records what the session drives."""

    def __init__(self, duration_ms: float = 60_000.0) -> None:
        self.opened: list[Path] = []
        self.duration_ms = duration_ms
        self.position_ms = 0.0
        self.eof = False
        self.paused = False
        self.ab_loop: tuple[float, float] | None = None
        self.seeks: list[float] = []
        self.speeds: list[float] = []
        self.closed = False

    def load(self, path: Path) -> None:
        self.opened.append(path)
        self.position_ms = 0.0
        self.eof = False

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_speed(self, speed: float) -> None:
        self.speeds.append(speed)

    def seek_ms(self, ms: float) -> None:
        self.position_ms = ms
        self.seeks.append(ms)

    def set_ab_loop(self, in_ms: float, out_ms: float) -> None:
        self.ab_loop = (in_ms, out_ms)

    def clear_ab_loop(self) -> None:
        self.ab_loop = None

    def close(self) -> None:
        self.closed = True


class FakeTCode:
    def __init__(self) -> None:
        self.updates: list[tuple[int, Funscript, float]] = []
        self.resets = 0
        self.closed = False

    def update(self, position_ms: int, fs: Funscript, *, speed: float = 1.0) -> None:
        self.updates.append((position_ms, fs, speed))

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


_FS_JSON = (
    '{"actions": [{"at": 0, "pos": 100}, {"at": 1000, "pos": 0},'
    ' {"at": 2000, "pos": 100}, {"at": 3000, "pos": 0}, {"at": 4000, "pos": 100}]}'
)


def _make_session(tmp_path, *, scripted=True, start_paused=False, duration_ms=60_000.0, entries=1):
    playlist = []
    for i in range(entries):
        vid = tmp_path / f"v{i}.mp4"
        vid.write_text("fake")
        fs = None
        if scripted:
            fs = tmp_path / f"v{i}.funscript"
            fs.write_text(_FS_JSON)
        playlist.append((vid, fs))
    player = FakePlayer(duration_ms=duration_ms)
    tcode = FakeTCode()
    session = PlayerSession(
        playlist, player=player, tcode=tcode, start_paused=start_paused,
    )
    return session, player, tcode


class TestFunscriptResting:
    def test_on_the_cluster_is_not_resting(self, tmp_path):
        session, player, _ = _make_session(tmp_path)  # dense action 0-4000ms
        player.position_ms = 2000.0

        assert session.funscript_resting is False

    def test_deep_in_a_gap_is_resting(self, tmp_path):
        session, player, _ = _make_session(tmp_path)
        player.position_ms = 20000.0  # long past the cluster and its buffer

        assert session.funscript_resting is True

    def test_unscripted_video_is_not_resting(self, tmp_path):
        session, player, _ = _make_session(tmp_path, scripted=False)
        player.position_ms = 20000.0

        assert session.funscript_resting is False


class TestLoadAndPlay:
    def test_init_loads_first_entry_and_plays(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        assert player.opened == [tmp_path / "v0.mp4"]
        assert player.paused is False
        assert session.has_funscript

    def test_init_start_paused_tells_player_to_pause(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, start_paused=True)

        assert session.is_paused
        assert player.paused is True

    def test_unscripted_entry_has_no_funscript(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, scripted=False)

        assert not session.has_funscript
        assert session.loop_state == "normal"

    def test_load_clears_any_previous_ab_loop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)
        player.ab_loop = (1.0, 2.0)

        session.step(1)

        assert player.ab_loop is None


class TestRecording:
    def test_record_gesture_without_funscript_sets_raw_ab_loop(self, tmp_path):
        # Unscripted videos can still be looped (clips): the raw marked range is
        # used, with no funscript snapping.
        session, player, tcode = _make_session(tmp_path, scripted=False)
        player.position_ms = 2500

        session.record_down()
        assert session.loop_state == "recording"

        player.position_ms = 3500
        session.record_up()

        assert session.loop_state == "looping"
        assert player.ab_loop == (2500, 3500)

    def test_release_before_start_floors_ab_loop_to_the_start(self, tmp_path):
        # If the out point lands before the start (the EOF-wrap race — seeks are
        # clamped to the start while marking), the loop floors to the start and
        # is handed to mpv as a minimum loop there, never flipped to [out, start].
        session, player, tcode = _make_session(tmp_path, scripted=False)
        player.position_ms = 5000
        session.record_down()

        player.position_ms = 2000  # out landed before the start (EOF-wrap race)
        session.record_up()

        assert session.loop_state == "looping"
        assert player.ab_loop == (5000, 5500)
        assert player.seeks[-1] == 5000  # jumps to the start, not back to 2000

    def test_record_gesture_sets_native_ab_loop_snapped_to_bases(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500

        session.record_down()
        assert session.loop_state == "recording"

        player.position_ms = 3500
        session.record_up()

        assert session.loop_state == "looping"
        # snapped to base actions (pos>=95) at 2000 and 4000
        assert player.ab_loop == (2000, 4000)
        assert player.seeks[-1] == 2000  # jumped to loop start
        assert tcode.resets >= 2

    def test_record_down_while_looping_cancels_and_clears_loop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500
        session.record_down()
        player.position_ms = 3500
        session.record_up()

        session.record_down()

        assert session.loop_state == "normal"
        assert player.ab_loop is None

    def test_loop_cancel_command_clears_active_loop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500
        session.record_down()
        player.position_ms = 3500
        session.record_up()

        session.loop_cancel()

        assert session.loop_state == "normal"
        assert player.ab_loop is None

    def test_loop_cancel_in_normal_is_noop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        session.loop_cancel()

        assert session.loop_state == "normal"


class TestRecordInMs:
    def test_exposes_in_point_only_while_recording(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        assert session.record_in_ms is None

        player.position_ms = 2500
        session.record_down()
        assert session.record_in_ms == 2500

        player.position_ms = 3500
        session.record_up()
        assert session.record_in_ms is None  # looping now, not marking


class TestLoopBounds:
    def test_none_while_not_looping(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        assert session.loop_bounds is None

    def test_none_without_funscript(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, scripted=False)
        assert session.loop_bounds is None

    def test_exposes_snapped_bounds_while_looping(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500
        session.record_down()
        player.position_ms = 3500
        session.record_up()

        assert session.loop_bounds == (2000, 4000)


class TestNavigation:
    def test_step_advances_and_wraps(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)

        session.step(1)
        assert player.opened[-1] == tmp_path / "v1.mp4"
        assert session.index == 1

        session.step(1)
        assert player.opened[-1] == tmp_path / "v0.mp4"
        assert session.index == 0

        session.step(-1)
        assert player.opened[-1] == tmp_path / "v1.mp4"

    def test_seek_by_clamps_and_resets_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, duration_ms=30_000)
        player.position_ms = 5_000
        resets_before = tcode.resets

        session.seek_by(-10_000)
        assert player.position_ms == 0
        assert tcode.resets == resets_before + 1

        player.position_ms = 5_000
        session.seek_by(50_000)
        assert player.position_ms == 30_000  # clamped to duration

    def test_seek_to_absolute_clamps_and_resets(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, duration_ms=30_000)

        session.seek_to(12_345)
        assert player.position_ms == 12_345

        session.seek_to(99_999)
        assert player.position_ms == 30_000
        session.seek_to(-5)
        assert player.position_ms == 0

    def test_seek_back_while_recording_stops_at_the_start(self, tmp_path):
        # While marking a loop you can't rewind before where it started: a
        # backward seek lands on the start point rather than before it.
        session, player, tcode = _make_session(tmp_path, duration_ms=60_000)
        player.position_ms = 5_000
        session.record_down()  # loop start = 5000

        session.seek_by(-3_000)  # would land at 2000
        assert player.position_ms == 5_000  # clamped up to the start

        session.seek_to(1_000)  # click-to-seek before the start
        assert player.position_ms == 5_000


class TestPause:
    def test_set_paused_tells_player(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        session.set_paused(True)
        assert session.is_paused
        assert player.paused is True

        session.set_paused(False)
        assert not session.is_paused
        assert player.paused is False

    def test_toggle_pause_flips(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        session.toggle_pause()
        assert session.is_paused
        session.toggle_pause()
        assert not session.is_paused

    def test_set_paused_same_state_is_noop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        session.set_paused(False)  # already playing
        # no assertion on player beyond not crashing; state unchanged
        assert not session.is_paused


class TestAdvance:
    def test_advance_updates_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 1500

        session.advance()

        assert tcode.updates and tcode.updates[-1][0] == 1500

    def test_advance_without_funscript_skips_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, scripted=False)
        player.position_ms = 1500

        session.advance()

        assert tcode.updates == []

    def test_advance_skips_tcode_when_disabled(self, tmp_path):
        # SET_TCODE_ENABLED 0 gates output so Genau can drive the OSR2 solo in
        # Hybrid mode without Nau's funscript T-Code double-driving the broker.
        session, player, tcode = _make_session(tmp_path)
        session.set_tcode_enabled(False)
        player.position_ms = 1500

        session.advance()

        assert tcode.updates == []

    def test_advance_resumes_tcode_when_re_enabled(self, tmp_path):
        # Leaving Hybrid (SET_TCODE_ENABLED 1) must let Nau drive its funscript
        # again, so the mute is a round-trip, not a one-way switch.
        session, player, tcode = _make_session(tmp_path)
        session.set_tcode_enabled(False)
        player.position_ms = 1500
        session.advance()
        assert tcode.updates == []

        session.set_tcode_enabled(True)
        player.position_ms = 1600
        session.advance()

        assert tcode.updates and tcode.updates[-1][0] == 1600

    def test_advance_while_paused_skips_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        session.set_paused(True)
        player.position_ms = 1500

        session.advance()

        assert tcode.updates == []

    def test_advance_resets_tcode_on_ab_loop_wrap(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500
        session.record_down()
        player.position_ms = 3500
        session.record_up()  # looping, last_pos tracked from here
        player.position_ms = 3900
        session.advance()
        resets_before = tcode.resets

        # mpv wraps B->A: position jumps backwards
        player.position_ms = 2000
        session.advance()

        assert tcode.resets == resets_before + 1

    def test_advance_finalizes_loop_at_eof_when_recording_wraps(self, tmp_path):
        # Recording a loop that runs off the end of the file: mpv (loop-file=inf)
        # rewinds the clock to the start.  Left alone, the next record_up would
        # capture an out point back near zero, inverting the loop so it replays
        # nothing.  Instead the session closes the loop at the end of the file
        # and starts looping normally.
        session, player, tcode = _make_session(
            tmp_path, scripted=False, duration_ms=10_000,
        )
        player.position_ms = 9_000
        session.record_down()
        assert session.loop_state == "recording"

        player.position_ms = 9_800
        session.advance()  # tracks last_pos near the end of the file

        player.position_ms = 20  # EOF hit: clock rewound to the start
        session.advance()

        assert session.loop_state == "looping"
        assert player.ab_loop == (9_000, 9_800)  # in..end, not in..~0
        assert player.seeks[-1] == 9_000  # jumped back to the loop start

    def test_advance_backward_seek_while_recording_keeps_marking(self, tmp_path):
        # A backward seek mid-record also rewinds the clock, but it does not land
        # at the start of the file, so it must not be mistaken for an EOF wrap:
        # recording continues rather than snapping the loop shut early.
        session, player, tcode = _make_session(
            tmp_path, scripted=False, duration_ms=60_000,
        )
        player.position_ms = 30_000
        session.record_down()
        player.position_ms = 40_000
        session.advance()

        player.position_ms = 20_000  # user seeked back 20s, still marking
        session.advance()

        assert session.loop_state == "recording"
        assert player.ab_loop is None

    def test_advance_at_end_auto_steps_in_normal(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)
        player.eof = True

        session.advance()

        assert session.index == 1

    def test_advance_at_end_does_not_step_while_looping(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        player.position_ms = 2500
        session.record_down()
        player.position_ms = 3500
        session.record_up()
        player.eof = True

        session.advance()

        assert session.index == 0

    def test_advance_at_end_auto_steps_unscripted(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, scripted=False, entries=2)
        player.eof = True

        session.advance()

        assert session.index == 1


class TestPassthroughs:
    def test_exposes_video_identity_and_duration(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        assert session.current_video == tmp_path / "v0.mp4"
        assert session.duration_ms == 60_000.0

    def test_exposes_loaded_funscript(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        assert isinstance(session.current_funscript, Funscript)

    def test_current_funscript_none_when_unscripted(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, scripted=False)
        assert session.current_funscript is None

    def test_close_closes_all_resources(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        session.close()

        assert tcode.closed
        assert player.closed


class TestPlayFile:
    def test_play_file_already_in_playlist_jumps_to_it(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=3)
        target = tmp_path / "v2.mp4"

        session.play_file(target, tmp_path / "v2.funscript")

        assert session.current_video == target
        assert session.index == 2

    def test_play_file_new_video_inserts_after_current(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)
        newv = tmp_path / "picked.mp4"
        newv.write_text("x")

        session.play_file(newv, None)

        assert session.current_video == newv
        assert session.index == 1
        assert session.playlist[1] == (newv, None)


class TestReplacePlaylist:
    def test_replace_keeps_current_video_position(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)
        v0, v1 = tmp_path / "v0.mp4", tmp_path / "v1.mp4"
        session.step(1)  # now on v1

        session.replace_playlist([(v0, None), (v1, None)])

        assert session.current_video == v1

    def test_replace_without_current_video_jumps_to_first(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        other = tmp_path / "other.mp4"
        other.write_text("x")

        session.replace_playlist([(other, None)])

        # A filtered-out current video must not linger on screen: playback jumps
        # straight to the new list's first entry, mirroring how the satellites
        # restart at item 0 when F-mode reloads them.
        assert session.current_video == other
        assert player.opened[-1] == other


class TestCycleVersion:
    def test_singleton_group_is_noop(self, tmp_path):
        vid = tmp_path / "solo.mp4"
        vid.write_text("x")
        player = FakePlayer()
        session = PlayerSession(
            [(vid, None)], player=player, tcode=FakeTCode(),
            version_index={vid: [(vid, None)]},
        )
        before = list(player.opened)
        session.cycle_version()
        assert player.opened == before

    def test_no_version_index_is_noop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        before = list(player.opened)
        session.cycle_version()
        assert player.opened == before

    def test_cycles_to_next_member_by_index_order(self, tmp_path):
        big = tmp_path / "Asa-1080p.mp4"
        small = tmp_path / "Asa-540.mp4"
        for p in (big, small):
            p.write_text("x")
        members = [(big, None), (small, None)]
        player = FakePlayer()
        session = PlayerSession(
            [(big, None)], player=player, tcode=FakeTCode(),
            version_index={big: members, small: members},
        )

        session.cycle_version()
        assert session.current_video == small

        session.cycle_version()
        assert session.current_video == big

    def test_replaces_in_place_so_navigation_skips_the_alternate(self, tmp_path):
        # Cycling a version must not add a playlist entry: [ still steps back to
        # the previous distinct video, not the version we cycled away from.
        x = tmp_path / "x.mp4"
        a1 = tmp_path / "Asa-1080p.mp4"
        a2 = tmp_path / "Asa-540.mp4"
        b = tmp_path / "b.mp4"
        for p in (x, a1, a2, b):
            p.write_text("x")
        members = [(a1, None), (a2, None)]
        player = FakePlayer()
        session = PlayerSession(
            [(x, None), (a1, None), (b, None)], player=player, tcode=FakeTCode(),
            version_index={a1: members, a2: members},
        )
        session.step(1)
        assert session.current_video == a1

        session.cycle_version()
        assert session.current_video == a2
        assert session.playlist == [(x, None), (a2, None), (b, None)]

        session.step(-1)
        assert session.current_video == x


class TestLoadPlaylist:
    def test_load_playlist_jumps_to_first_of_new_list(self, tmp_path):
        session, player, tcode = _make_session(tmp_path, entries=2)
        a = tmp_path / "a.mp4"; a.write_text("x")
        b = tmp_path / "b.mp4"; b.write_text("x")

        session.load_playlist([(a, None), (b, None)])

        assert session.index == 0
        assert session.current_video == a
        assert player.opened[-1] == a

    def test_load_playlist_empty_is_noop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        before = session.current_video
        session.load_playlist([])
        assert session.current_video == before


class TestSpeed:
    def test_speed_defaults_to_normal(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        assert session.speed == 1.0

    def test_set_speed_drives_player_and_resets_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        resets_before = tcode.resets

        session.set_speed(1.5)

        assert session.speed == 1.5
        assert player.speeds[-1] == 1.5
        assert tcode.resets == resets_before + 1  # re-time the in-flight move

    def test_set_speed_clamps_to_supported_range(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        session.set_speed(99.0)
        assert session.speed == MAX_SPEED_RATE

        session.set_speed(0.001)
        assert session.speed == MIN_SPEED_RATE

    def test_adjust_speed_steps_relative_and_clamps(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)

        session.adjust_speed(0.5)
        assert session.speed == 1.5

        session.adjust_speed(-1.0)
        assert session.speed == 0.5

    def test_set_speed_same_value_is_noop(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        resets_before = tcode.resets

        session.set_speed(1.0)  # already normal

        assert player.speeds == []  # no redundant player call
        assert tcode.resets == resets_before

    def test_advance_passes_current_speed_to_tcode(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        session.set_speed(2.0)
        player.position_ms = 1500

        session.advance()

        assert tcode.updates[-1] == (1500, session.current_funscript, 2.0)
