from __future__ import annotations

from pathlib import Path

from nau.funscript import Funscript
from nau.session import PlayerSession


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
        self.closed = False

    def load(self, path: Path) -> None:
        self.opened.append(path)
        self.position_ms = 0.0
        self.eof = False

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

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
        self.updates: list[tuple[int, Funscript]] = []
        self.resets = 0
        self.closed = False

    def update(self, position_ms: int, fs: Funscript) -> None:
        self.updates.append((position_ms, fs))

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

    def test_replace_without_current_video_steps_to_first(self, tmp_path):
        session, player, tcode = _make_session(tmp_path)
        other = tmp_path / "other.mp4"
        other.write_text("x")

        session.replace_playlist([(other, None)])

        session.step(1)
        assert session.current_video == other


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
