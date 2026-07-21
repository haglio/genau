from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nau import clip_match
from nau.clip_match import (
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    align,
    frame_hashes,
    locate,
    match_library,
    record,
)
from nau.clip_nav import read_clip
from nau.library import LibraryEntry


def _hashes(n: int, seed: int = 0) -> np.ndarray:
    """A run of *n* distinct frame hashes, as an unrelated video would give."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2**64, size=n, dtype=np.uint64)


class TestFrameHashes:
    def test_a_dimmer_copy_of_a_frame_hashes_the_same(self):
        """The clip and the scene are different encodes of one picture, so what
        the hash reads has to be the shape of the frame, not its exposure."""
        rng = np.random.default_rng(3)
        frames = rng.integers(40, 200, size=(5, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert list(frame_hashes(frames - 20)) == list(frame_hashes(frames))

    def test_a_video_ffmpeg_could_not_read_hashes_to_nothing(self):
        """One unreadable file among hundreds must cost that file its match, not
        the whole batch."""
        nothing = np.empty((0, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(frame_hashes(nothing)) == 0
        assert align(frame_hashes(nothing), _hashes(400), fps=8.0) is None

    def test_different_frames_hash_differently(self):
        rng = np.random.default_rng(4)
        frames = rng.integers(0, 256, size=(20, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(set(frame_hashes(frames).tolist())) == 20


class TestAlign:
    def test_finds_where_the_excerpt_sits(self):
        scene = _hashes(400)
        clip = scene[120:160]

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.offset == 15.0

    def test_a_clip_from_elsewhere_does_not_align(self):
        """Frames of unrelated videos collide often enough at this tolerance —
        two performers on one bed look alike pooled down to 72 cells. What
        scattered collisions cannot do is agree on a single offset."""
        clip, scene = _hashes(40, seed=1), _hashes(400, seed=2)
        for clip_frame, scene_frame in ((3, 17), (11, 250), (12, 88), (30, 301), (37, 130)):
            scene[scene_frame] = clip[clip_frame]

        assert align(clip, scene, fps=8.0) is None

    def test_counts_an_excerpt_that_jitters_by_a_frame(self):
        """Sampling 8 a second off a 24fps scene lands on exact source frames; off
        a 30fps clip it does not, so consecutive frames of one excerpt answer to
        offsets a bucket apart. Scoring only the single best bucket read a real
        match — a 4:3 scene against its 16:9 clip — as 31% of itself."""
        scene = _hashes(400)
        clip = np.array([scene[200 + i + (i % 2)] for i in range(40)], dtype=np.uint64)

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.score == 1.0
        assert abs(found.offset - 25.0) <= 1 / 8


class TestLocate:
    def test_picks_the_candidate_whose_frames_are_in_the_scene(self):
        scene = _hashes(400)
        candidates = {
            Path("wrong.mp4"): _hashes(40, seed=7),
            Path("right.mp4"): scene[200:240],
            Path("also wrong.mp4"): _hashes(40, seed=8),
        }

        found = locate(scene, candidates, fps=8.0)

        assert found is not None
        assert found.clip == Path("right.mp4")
        assert found.offset == 25.0

    def test_no_candidate_belongs_to_this_scene(self):
        """~79 of the library's scenes were never in a compilation; a performer
        with several scenes still offers their other clips as candidates, and
        every one of them has to be turned down."""
        candidates = {Path(f"{i}.mp4"): _hashes(40, seed=10 + i) for i in range(3)}

        assert locate(_hashes(400), candidates, fps=8.0) is None


class TestRecord:
    def test_writes_the_answer_into_the_clip_sidecar(self, tmp_path):
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = lib / "w" / "Nora Quill - Nights of Nonsense 8.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"x")
        sidecar = meta / "w" / "Nora Quill - Nights of Nonsense 8.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text(json.dumps({
            "version": {"group": "Nora Quill - Nights of Nonsense 8", "processed": False},
            "video": {"action": "Alpha"},
            "clip": {"compilation": "Vol1", "index": 9, "performer": "Nora Quill"},
        }), encoding="utf-8")
        scene = lib / "other" / "Mia-Vale_540-izB4YKFa.mp4"

        record(clip, scene, offset=808.25, metadata_root=meta)

        assert read_clip(clip, meta) == {
            "compilation": "Vol1", "index": 9, "performer": "Nora Quill",
            "full_video": str(scene), "scene_offset": 808.25,
        }
        assert json.loads(sidecar.read_text(encoding="utf-8"))["video"] == {"action": "Alpha"}


def _frames(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(count, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)


class TestMatchLibrary:
    def _library(self, tmp_path):
        """A performer with one scene (in two versions) and two of her clips."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        entries = []
        for rel, size, payload in (
            ("other/Mia-Vale_540-izB4YKFa.mp4", 100, {}),
            ("other/Mia-Vale_540-izB4YKFa_apo8_iris2.mp4", 400, {}),
            ("w/Nora Quill - Nights of Nonsense 8.mp4", 50,
             {"clip": {"compilation": "Vol1", "index": 9, "performer": "Nora Quill"}}),
            ("w/Nora Quill - Scene Three 3.mp4", 50,
             {"clip": {"compilation": "Vol4", "index": 2, "performer": "Nora Quill"}}),
        ):
            video = lib / rel
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"x" * size)
            sidecar = (meta / rel).with_suffix(".json")
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            entries.append(LibraryEntry(video=video, funscript=None, size=size))
        return lib, meta, entries

    def test_records_the_scene_each_clip_was_cut_from(self, tmp_path):
        lib, meta, entries = self._library(tmp_path)
        scene_frames = _frames(400, seed=1)

        def sampler(video, fps):
            if video.name.startswith("Nora Quill"):
                return scene_frames
            if "Angels" in video.name:
                return scene_frames[80:120]
            return _frames(40, seed=2)

        matched = match_library(entries, meta, fps=8.0, sampler=sampler)

        cut_from_it = lib / "w" / "Nora Quill - Nights of Nonsense 8.mp4"
        scene = lib / "other" / "Mia-Vale_540-izB4YKFa.mp4"
        assert list(matched) == [scene]
        assert matched[scene].clip == cut_from_it
        assert read_clip(cut_from_it, meta)["scene_offset"] == 10.0
        assert read_clip(cut_from_it, meta)["full_video"] == str(scene)
        assert "full_video" not in read_clip(lib / "w" / "Nora Quill - Scene Three 3.mp4", meta)

    def test_decodes_the_cheapest_version_of_a_scene(self, tmp_path):
        """Upscales cost minutes where the original costs seconds, and they hold
        the same pictures, so only the smallest file of a family is ever read."""
        _, meta, entries = self._library(tmp_path)
        sampled = []

        def sampler(video, fps):
            sampled.append(video)
            return _frames(40, seed=3)

        match_library(entries, meta, fps=8.0, sampler=sampler)

        assert not any("apo8" in v.name for v in sampled)

    def test_the_better_alignment_takes_a_clip_two_scenes_both_hold(self, tmp_path):
        """The library keeps a 540p release and a 4k re-release of one scene, cut
        to different lengths, and the clip is genuinely inside both. Only one can
        be its full_video, so the closer alignment gets it rather than whichever
        scene the sweep reached last."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        entries = []
        for rel, payload in (
            ("other/redacted_540-pacI21CK.mp4",
             {"version": {"group": "redacted_540-pacI21CK"}}),
            ("other/redacted POV BJ 4k 60fps.mp4",
             {"version": {"group": "redacted POV BJ 4k 60fps"}}),
            ("w/redacted - Scene Three 8.mp4",
             {"clip": {"compilation": "Vol7", "index": 4, "performer": "redacted"}}),
        ):
            video = lib / rel
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"x")
            sidecar = (meta / rel).with_suffix(".json")
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            entries.append(LibraryEntry(video=video, funscript=None, size=1))
        release_540 = _frames(400, seed=6)
        clip_frames = release_540[80:120]

        def sampler(video, fps):
            if video.name.startswith("redacted_540"):
                return release_540
            if video.name.endswith("60fps.mp4"):  # same scene, trimmed, half of it
                return np.concatenate([_frames(24, seed=9), clip_frames[:20]])
            return clip_frames

        matched = match_library(entries, meta, fps=8.0, sampler=sampler)

        scene = lib / "other" / "redacted_540-pacI21CK.mp4"
        assert list(matched) == [scene]
        clip = lib / "w" / "redacted - Scene Three 8.mp4"
        assert read_clip(clip, meta)["full_video"] == str(scene)
        assert read_clip(clip, meta)["scene_offset"] == 10.0

    def test_separates_scenes_evolver_calls_different_versions(self, tmp_path):
        """Two scenes of one performer can share a name prefix without being the
        same video — "redacted_540-hash" and "redacted POV BJ 4k".
        Folding them would decode one and leave the other unmatchable, so the
        version group Evolver recorded decides, not the names."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        entries = []
        for rel, payload in (
            ("other/redacted_540-pacI21CK.mp4",
             {"version": {"group": "redacted_540-pacI21CK"}}),
            ("other/redacted POV BJ 4k 60fps.mp4",
             {"version": {"group": "redacted POV BJ 4k 60fps"}}),
            ("w/redacted - Scene Three 8.mp4",
             {"clip": {"compilation": "Vol7", "index": 4, "performer": "redacted"}}),
        ):
            video = lib / rel
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"x")
            sidecar = (meta / rel).with_suffix(".json")
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            entries.append(LibraryEntry(video=video, funscript=None, size=1))
        scenes = []

        def sampler(video, fps):
            if video.parent.name == "other":
                scenes.append(video)
            return _frames(4, seed=5)

        match_library(entries, meta, fps=8.0, sampler=sampler)

        assert len(scenes) == 2


class TestMain:
    def test_runs_over_the_library_the_config_names(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "genau_config.json"
        config.write_text(json.dumps({"nau": {
            "videos_dir": str(tmp_path / "videos" / "videos"),
            "scripts_dir": str(tmp_path / "scripts"),
            "metadata_dir": str(tmp_path / "videos" / "metadata"),
        }}), encoding="utf-8")
        (tmp_path / "videos" / "videos").mkdir(parents=True)
        seen = {}
        monkeypatch.setattr(
            clip_match, "match_library",
            lambda entries, metadata_root, **kw: seen.update(root=metadata_root) or {},
        )

        assert clip_match.main(["--config", str(config)]) == 0
        assert seen["root"] == tmp_path / "videos" / "metadata"
        assert "0 scenes matched" in capsys.readouterr().out

    def test_refuses_a_config_that_names_no_library(self, tmp_path):
        config = tmp_path / "genau_config.json"
        config.write_text(json.dumps({"nau": {"videos_dir": "x"}}), encoding="utf-8")

        with pytest.raises(SystemExit):
            clip_match.main(["--config", str(config)])
