from __future__ import annotations

from pathlib import Path

from satellite.session import SatelliteSession


class FakePlayer:
    """Stand-in for the mpv-backed player: records what the session drives.

    Trimmed from Nau's FakePlayer — a satellite is silent and unscripted, so
    there is no volume, speed, funscript or A/B-loop surface to fake.
    """

    def __init__(self, duration_ms: float = 5_000.0) -> None:
        self.opened: list[Path] = []
        self.duration_ms = duration_ms
        self.position_ms = 0.0
        self.eof = False
        self.paused = False
        self.loop_file = False
        self.seeks: list[float] = []
        self.closed = False

    def load(self, path: Path) -> None:
        self.opened.append(path)
        self.position_ms = 0.0
        self.eof = False

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_loop_file(self, loop: bool) -> None:
        self.loop_file = loop

    def seek_ms(self, ms: float) -> None:
        self.position_ms = ms
        self.seeks.append(ms)

    def close(self) -> None:
        self.closed = True


def _make_session(tmp_path, *, entries=1, start_paused=False, duration_ms=5_000.0):
    playlist = []
    for i in range(entries):
        vid = tmp_path / f"v{i}.mp4"
        vid.write_text("fake")
        playlist.append(vid)
    player = FakePlayer(duration_ms=duration_ms)
    session = SatelliteSession(playlist, player=player, start_paused=start_paused)
    return session, player


class TestLoadAndPlay:
    def test_init_loads_first_entry_and_plays(self, tmp_path):
        session, player = _make_session(tmp_path)

        assert player.opened == [tmp_path / "v0.mp4"]
        assert player.paused is False
        assert session.current_video == tmp_path / "v0.mp4"
        assert session.index == 0

    def test_init_start_paused_tells_player_to_pause(self, tmp_path):
        session, player = _make_session(tmp_path, start_paused=True)

        assert session.is_paused
        assert player.paused is True


class TestNavigation:
    def test_step_advances_and_wraps(self, tmp_path):
        session, player = _make_session(tmp_path, entries=2)

        session.step(1)
        assert player.opened[-1] == tmp_path / "v1.mp4"
        assert session.index == 1

        session.step(1)
        assert player.opened[-1] == tmp_path / "v0.mp4"  # wraps forward
        assert session.index == 0

        session.step(-1)
        assert player.opened[-1] == tmp_path / "v1.mp4"  # wraps backward


class TestPause:
    def test_set_paused_drives_the_player(self, tmp_path):
        session, player = _make_session(tmp_path)

        session.set_paused(True)
        assert session.is_paused
        assert player.paused is True

        session.set_paused(False)
        assert not session.is_paused
        assert player.paused is False

    def test_toggle_pause_flips(self, tmp_path):
        session, player = _make_session(tmp_path)

        session.toggle_pause()
        assert session.is_paused
        session.toggle_pause()
        assert not session.is_paused


class TestAdvance:
    def test_advance_at_eof_steps_to_next(self, tmp_path):
        session, player = _make_session(tmp_path, entries=2)
        player.eof = True

        session.advance()

        assert session.index == 1

    def test_advance_before_eof_is_a_noop(self, tmp_path):
        session, player = _make_session(tmp_path, entries=2)

        session.advance()

        assert session.index == 0

    def test_advance_while_paused_never_steps(self, tmp_path):
        # The OmniPause guarantee: a paused satellite cannot walk its playlist,
        # so there is no VLC-style "resumed on its own" storm to police.
        session, player = _make_session(tmp_path, entries=2)
        session.set_paused(True)
        player.eof = True

        session.advance()

        assert session.index == 0


class TestLock:
    def test_locked_satellite_repeats_the_same_clip_at_eof(self, tmp_path):
        session, player = _make_session(tmp_path, entries=2)
        session.set_locked(True)
        assert session.is_locked

        player.eof = True
        session.advance()

        assert session.index == 0  # repeat-one: stays on the locked clip

    def test_lock_engages_native_loop_for_seamless_repeat(self, tmp_path):
        # mpv loops the file itself (loop_file=inf) so a locked short clip repeats
        # without the reload flicker a seek-to-zero would show.
        session, player = _make_session(tmp_path)

        session.set_locked(True)
        assert player.loop_file is True

        session.set_locked(False)
        assert player.loop_file is False

    def test_unlocked_satellite_advances_again(self, tmp_path):
        session, player = _make_session(tmp_path, entries=2)
        session.set_locked(True)
        session.set_locked(False)

        player.eof = True
        session.advance()

        assert session.index == 1


class TestDiscard:
    def test_discard_removes_current_and_plays_next(self, tmp_path):
        session, player = _make_session(tmp_path, entries=3)  # on v0

        session.discard()

        assert session.current_video == tmp_path / "v1.mp4"
        assert [p.name for p in session.playlist] == ["v1.mp4", "v2.mp4"]
        assert player.opened[-1] == tmp_path / "v1.mp4"

    def test_discard_on_the_last_entry_wraps_to_the_first(self, tmp_path):
        session, player = _make_session(tmp_path, entries=3)
        session.step(2)  # on v2, the last

        session.discard()

        assert session.current_video == tmp_path / "v0.mp4"
        assert [p.name for p in session.playlist] == ["v0.mp4", "v1.mp4"]

    def test_discard_of_the_only_clip_is_a_noop(self, tmp_path):
        # A satellite must never be left with an empty playlist; the last clip
        # cannot be discarded.
        session, player = _make_session(tmp_path, entries=1)
        opened_before = list(player.opened)

        session.discard()

        assert len(session.playlist) == 1
        assert player.opened == opened_before
