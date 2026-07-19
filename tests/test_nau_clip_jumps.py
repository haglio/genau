"""The playlist moves a clip's sidecar makes possible, and the state one leaves."""
from __future__ import annotations

import json
from pathlib import Path

from nau.clip_jumps import ClipJumps
from nau.clip_nav import ClipNav


def _clip(lib: Path, meta: Path, rel: str, comp: str, index: int,
          source: str, performer: str) -> Path:
    video = lib / rel
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"x")
    sidecar = (meta / video.relative_to(lib)).with_suffix(".json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({
        "clip": {"compilation": comp, "index": index,
                 "source": source, "performer": performer},
    }), encoding="utf-8")
    return video


class FakeSession:
    """Records the playlist moves the jumps drive."""

    def __init__(self, current: Path, playlist=None) -> None:
        self.current_video = current
        self.playlist = list(playlist or [(current, None)])
        self.replaced: list[list[tuple[Path, Path | None]]] = []
        self.played: list[tuple[Path, Path | None]] = []

    def replace_playlist(self, playlist) -> None:
        self.replaced.append(list(playlist))
        self.playlist = list(playlist)

    def play_file(self, video: Path, funscript: Path | None) -> None:
        self.played.append((video, funscript))


class FakeNotices:
    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def say(self, message: str, *, level: str = "error") -> bool:
        self.said.append((message, level))
        return True


def _world(tmp_path: Path):
    """A Vol6 compilation of two clips, plus the scene one was taken from."""
    lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    first = _clip(lib, meta, "w/Jane Doe - Pound Region A 2.mp4", "Vol6", 1,
                  "Pound Region A 2", "Jane Doe")
    second = _clip(lib, meta, "w/Kim Lee - POV Scene 2.mp4", "Vol6", 9,
                   "POV Scene 2", "Kim Lee")
    scene = lib / "other" / "POV Scene 2 - Kim Lee 1080p.mp4"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_bytes(b"x")
    nav = ClipNav.build([first, second, scene], meta)
    return nav, first, second, scene


def _jumps(nav, current: Path, funscripts=None, playlist=None):
    session = FakeSession(current, playlist)
    notices = FakeNotices()
    return ClipJumps(nav, session, funscripts or {}, notices), session, notices


class TestResume:
    """Fun Time resumes the playlist a session closed on, so Nau can reopen
    inside a compilation without ever having been told it entered one."""

    def test_a_resumed_compilation_playlist_is_recognised(self, tmp_path):
        nav, first, second, _scene = _world(tmp_path)
        # Resume rotates the list to the video that was on screen, so the order
        # differs from the one PLAY_COMPILATION installed.
        jumps, _session, _notices = _jumps(
            nav, second, playlist=[(second, None), (first, None)])

        jumps.resume()

        assert jumps.compilation == "Vol6"

    def test_an_ordinary_playlist_is_not_mistaken_for_one(self, tmp_path):
        """A clip can turn up in a normal browse; being on one is not being
        inside its compilation."""
        nav, first, second, scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(
            nav, second, playlist=[(second, None), (scene, None)])

        jumps.resume()

        assert jumps.compilation == ""

    def test_a_playlist_holding_only_part_of_one_is_not_it(self, tmp_path):
        nav, _first, second, _scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(nav, second, playlist=[(second, None)])

        jumps.resume()

        assert jumps.compilation == ""

    def test_a_non_clip_resumes_to_nothing(self, tmp_path):
        nav, _first, _second, scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(nav, scene)

        jumps.resume()

        assert jumps.compilation == ""


class TestPlayCompilation:
    def test_swaps_the_playlist_for_the_volume_in_order(self, tmp_path):
        nav, first, second, _scene = _world(tmp_path)
        jumps, session, notices = _jumps(nav, second)

        jumps.play_compilation()

        assert [video for video, _fs in session.replaced[0]] == [first, second]
        assert notices.said == [("compilation: 2 clips", "notice")]

    def test_remembers_which_compilation_is_holding_the_playlist(self, tmp_path):
        """The HUD reports this; it is the state the player could get stuck in
        with nothing on screen naming it."""
        nav, _first, second, _scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(nav, second)

        assert jumps.compilation == ""
        jumps.play_compilation()
        assert jumps.compilation == "Vol6"

    def test_a_non_clip_says_so_and_leaves_the_playlist_alone(self, tmp_path):
        nav, _first, _second, scene = _world(tmp_path)
        jumps, session, notices = _jumps(nav, scene)

        jumps.play_compilation()

        assert session.replaced == []
        assert notices.said == [("not a compilation clip", "error")]
        assert jumps.compilation == ""

    def test_leaving_forgets_it(self, tmp_path):
        """Saying "shorts" or reloading rebuilds the playlist from elsewhere, so
        the compilation is no longer what is on screen."""
        nav, _first, second, _scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(nav, second)
        jumps.play_compilation()

        jumps.leave_compilation()

        assert jumps.compilation == ""


class TestSingleVideoJumps:
    def test_full_vid_plays_the_scene_the_clip_came_from(self, tmp_path):
        nav, _first, second, scene = _world(tmp_path)
        script = tmp_path / "scene.funscript"
        jumps, session, notices = _jumps(nav, second, {scene: script})

        jumps.play_full_vid()

        assert session.played == [(scene, script)]
        assert notices.said == [("full video", "notice")]

    def test_money_shot_plays_the_clip_carved_from_the_scene(self, tmp_path):
        nav, _first, second, scene = _world(tmp_path)
        jumps, session, notices = _jumps(nav, scene)

        jumps.play_money_shot()

        assert session.played == [(second, None)]
        assert notices.said == [("money shot", "notice")]

    def test_a_miss_says_so_rather_than_moving(self, tmp_path):
        """Most clips' source movies are not in the library at all, so having
        nowhere to go is the ordinary case — and silence is what left the player
        looking broken."""
        nav, first, _second, _scene = _world(tmp_path)
        jumps, session, notices = _jumps(nav, first)

        jumps.play_full_vid()

        assert session.played == []
        assert notices.said == [("full video not available", "error")]

    def test_neither_jump_disturbs_the_compilation_it_is_inside(self, tmp_path):
        """These two move to one video; only "compilation" replaces the playlist,
        so the HUD must keep naming the volume you are still walking."""
        nav, _first, second, _scene = _world(tmp_path)
        jumps, _session, _notices = _jumps(nav, second)
        jumps.play_compilation()

        jumps.play_full_vid()

        assert jumps.compilation == "Vol6"
