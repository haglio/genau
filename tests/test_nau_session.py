from __future__ import annotations

from pathlib import Path

import numpy as np

from nau.funscript import Funscript
from nau.playback import PlaybackClock
from nau.session import PlayerSession


class FakeVideo:
    def __init__(self, duration_ms: float = 60_000.0) -> None:
        self.opened: list[Path] = []
        self.duration_ms = duration_ms
        self.fps = 30.0
        self.ended = False
        self.last_frame = np.zeros((2, 2, 3), dtype=np.uint8)
        self.frame = np.ones((2, 2, 3), dtype=np.uint8)
        self.closed = False

    def open(self, path: Path) -> None:
        self.opened.append(path)

    def read_frame_at(self, target_ms: float) -> np.ndarray:
        return self.frame

    def close(self) -> None:
        self.closed = True


class FakeAudio:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def load(self, path: Path) -> None:
        self.calls.append(("load", path))

    def play(self, start_ms: float = 0) -> None:
        self.calls.append(("play", start_ms))

    def pause(self) -> None:
        self.calls.append(("pause",))

    def resume(self) -> None:
        self.calls.append(("resume",))

    def seek(self, ms: float) -> None:
        self.calls.append(("seek", ms))

    def start_loop(self, in_ms: int, out_ms: int) -> None:
        self.calls.append(("start_loop", in_ms, out_ms))

    def stop_loop(self, resume_ms: float) -> None:
        self.calls.append(("stop_loop", resume_ms))

    def close(self) -> None:
        self.calls.append(("close",))

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


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


class Clock:
    """Manual monotonic time source."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


_FS_JSON = '{"actions": [{"at": 0, "pos": 100}, {"at": 1000, "pos": 0}, {"at": 2000, "pos": 100}, {"at": 3000, "pos": 0}, {"at": 4000, "pos": 100}]}'


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
    video = FakeVideo(duration_ms=duration_ms)
    audio = FakeAudio()
    tcode = FakeTCode()
    now = Clock()
    clock = PlaybackClock(now_source=now)
    session = PlayerSession(
        playlist, video=video, audio=audio, clock=clock, tcode=tcode,
        start_paused=start_paused,
    )
    return session, video, audio, tcode, now


class TestLoadAndPlay:
    def test_init_loads_first_entry_and_starts_playing(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        assert video.opened == [tmp_path / "v0.mp4"]
        assert ("load", tmp_path / "v0.mp4") in audio.calls
        assert ("play", 0) in audio.calls
        assert not session.is_paused
        assert session.has_funscript

    def test_init_start_paused_does_not_start_playback(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, start_paused=True)

        assert session.is_paused
        assert "play" not in audio.names()
        assert session.position_ms == 0

    def test_unscripted_entry_has_no_funscript(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False)

        assert not session.has_funscript
        assert session.loop_state == "normal"


class TestRecording:
    def test_record_down_without_funscript_is_noop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False)

        session.record_down()
        session.record_up()

        assert session.loop_state == "normal"
        assert audio.names().count("start_loop") == 0

    def test_record_gesture_creates_snapped_loop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5  # position 2500ms

        session.record_down()
        assert session.loop_state == "recording"

        now.t = 3.5
        session.record_up()

        assert session.loop_state == "looping"
        # snapped to base actions (pos>=95) at 2000 and 4000
        assert ("start_loop", 2000, 4000) in audio.calls
        assert session.position_ms == 2000
        assert tcode.resets >= 2  # once on load, once on loop start

    def test_record_down_while_looping_cancels(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()

        session.record_down()

        assert session.loop_state == "normal"
        assert audio.names().count("stop_loop") == 1

    def test_loop_cancel_command_cancels_active_loop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()

        session.loop_cancel()

        assert session.loop_state == "normal"
        assert audio.names().count("stop_loop") == 1

    def test_loop_cancel_in_normal_is_noop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        session.loop_cancel()

        assert session.loop_state == "normal"
        assert "stop_loop" not in audio.names()


class TestLoopBounds:
    def test_none_while_not_looping(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        assert session.loop_bounds is None  # normal

        now.t = 2.5
        session.record_down()
        assert session.loop_bounds is None  # still marking

    def test_none_without_funscript(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False)

        assert session.loop_bounds is None

    def test_exposes_snapped_bounds_while_looping(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()

        assert session.loop_bounds == (2000, 4000)

        session.loop_cancel()
        assert session.loop_bounds is None


class TestNavigation:
    def test_step_advances_and_wraps(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=2)

        session.step(1)
        assert video.opened[-1] == tmp_path / "v1.mp4"
        assert session.index == 1

        session.step(1)
        assert video.opened[-1] == tmp_path / "v0.mp4"
        assert session.index == 0

        session.step(-1)
        assert video.opened[-1] == tmp_path / "v1.mp4"

    def test_seek_by_clamps_and_resets_tcode(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, duration_ms=30_000)
        now.t = 5.0
        resets_before = tcode.resets

        session.seek_by(-10_000)
        assert session.position_ms == 0
        assert ("seek", 0) in audio.calls
        assert tcode.resets == resets_before + 1

        session.seek_by(50_000)
        assert session.position_ms == 30_000


class TestPause:
    def test_set_paused_pauses_clock_and_audio(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 5.0

        session.set_paused(True)

        assert session.is_paused
        assert "pause" in audio.names()
        pos = session.position_ms
        now.t = 7.0
        assert session.position_ms == pos

    def test_set_paused_false_resumes_audio(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        session.set_paused(True)

        session.set_paused(False)

        assert not session.is_paused
        assert "resume" in audio.names()

    def test_resume_after_paused_load_starts_audio_from_position(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, start_paused=True)

        session.set_paused(False)

        # audio never play()ed for this file, so unpause alone would be silent
        assert ("play", 0) in audio.calls or ("seek", 0) in audio.calls
        assert "resume" not in audio.names()

    def test_set_paused_same_state_is_noop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        calls_before = len(audio.calls)

        session.set_paused(False)

        assert len(audio.calls) == calls_before

    def test_seek_while_paused_is_silent_until_resume(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 5.0
        session.set_paused(True)
        calls_before = len(audio.calls)

        session.seek_by(10_000)

        assert audio.calls[calls_before:] == []  # nothing audible while paused
        assert session.position_ms == 15_000

        session.set_paused(False)
        assert audio.calls[calls_before:] == [("play", 15_000)]

    def test_record_gesture_while_paused_defers_loop_audio_to_resume(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.set_paused(True)
        calls_before = len(audio.calls)

        session.record_down()
        session.record_up()

        assert session.loop_state == "looping"
        assert session.loop_bounds == (2000, 4000)
        assert audio.calls[calls_before:] == []  # nothing audible while paused

        session.set_paused(False)
        assert audio.calls[calls_before:] == [("start_loop", 2000, 4000)]

    def test_loop_cancel_while_paused_defers_audio_to_resume(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()  # looping 2000-4000, clock seeked to 2000
        now.t = 4.0  # position 2500 inside the loop
        session.set_paused(True)
        calls_before = len(audio.calls)

        session.loop_cancel()

        assert session.loop_state == "normal"
        assert audio.calls[calls_before:] == []  # no stop_loop seek while paused

        session.set_paused(False)
        assert audio.calls[calls_before:] == [("play", 2500)]


class TestAdvance:
    def test_advance_updates_tcode_and_returns_frame(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 1.5

        frame = session.advance()

        assert frame is video.frame
        assert tcode.updates and tcode.updates[-1][0] == 1500

    def test_advance_without_funscript_skips_tcode(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False)
        now.t = 1.5

        frame = session.advance()

        assert frame is video.frame
        assert tcode.updates == []

    def test_advance_while_paused_returns_last_frame(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        session.set_paused(True)

        frame = session.advance()

        assert frame is video.last_frame
        assert tcode.updates == []

    def test_advance_wraps_active_loop(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()  # loop 2000-4000, clock seeked to 2000

        now.t = 3.5 + 2.1  # position 2000 + 2100 = past out point 4000

        session.advance()

        assert session.position_ms == 2000
        assert tcode.updates[-1][0] == 2000

    def test_advance_at_end_auto_steps_in_normal(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=2)
        video.ended = True

        session.advance()

        assert session.index == 1

    def test_advance_at_end_does_not_step_while_looping(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)
        now.t = 2.5
        session.record_down()
        now.t = 3.5
        session.record_up()
        video.ended = True

        session.advance()

        assert session.index == 0

    def test_advance_at_end_auto_steps_unscripted(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False, entries=2)
        video.ended = True

        session.advance()

        assert session.index == 1


class TestPassthroughs:
    def test_exposes_video_identity_and_fps(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        assert session.current_video == tmp_path / "v0.mp4"
        assert session.fps == 30.0
        assert session.duration_ms == 60_000.0

    def test_exposes_loaded_funscript(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        fs = session.current_funscript
        assert fs is not None
        assert fs.actions[0] == (0, 100)

    def test_current_funscript_none_when_unscripted(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, scripted=False)

        assert session.current_funscript is None

    def test_close_closes_all_resources(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path)

        session.close()

        assert tcode.closed
        assert video.closed
        assert ("close",) in audio.calls


class TestPlayFile:
    def test_play_file_already_in_playlist_jumps_to_it(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=3)
        target = tmp_path / "v2.mp4"

        session.play_file(target, None)

        assert session.index == 2
        assert video.opened[-1] == target
        assert len(session.playlist) == 3

    def test_play_file_new_video_inserts_after_current(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=2)
        new_vid = tmp_path / "extra.mp4"
        new_vid.write_text("fake")
        new_fs = tmp_path / "extra.funscript"
        new_fs.write_text(_FS_JSON)

        session.play_file(new_vid, new_fs)

        assert video.opened[-1] == new_vid
        assert session.has_funscript
        assert session.playlist[1] == (new_vid, new_fs)
        # next continues into the original order
        session.step(1)
        assert video.opened[-1] == tmp_path / "v1.mp4"


class TestReplacePlaylist:
    def test_replace_keeps_current_video_position(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=3)
        session.step(1)  # now on v1
        new_list = [
            (tmp_path / "v2.mp4", None),
            (tmp_path / "v1.mp4", None),
        ]

        session.replace_playlist(new_list)

        assert session.index == 1  # v1 found in new list
        assert video.opened[-1] == tmp_path / "v1.mp4"  # no reload

    def test_replace_without_current_video_steps_to_first(self, tmp_path):
        session, video, audio, tcode, now = _make_session(tmp_path, entries=2)
        new_list = [(tmp_path / "other.mp4", None)]

        session.replace_playlist(new_list)

        # The playing video is not interrupted and still reports correctly
        assert session.current_video == tmp_path / "v0.mp4"

        session.step(1)
        assert video.opened[-1] == tmp_path / "other.mp4"
