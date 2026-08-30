from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nau import clip_match
from nau.clip_match import (
    MIN_PICTURE_FRACTION,
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    align,
    frame_hashes,
    locate,
    match_library,
    picture_box,
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


class TestPictureBox:
    """What to crop off a frame, read out of ffmpeg's cropdetect reports."""

    def _report(self, width: int, height: int, x: int = 0, y: int = 0) -> str:
        return (
            f"[Parsed_cropdetect_0 @ 000] x1:{x} x2:0 y1:{y} y2:0 w:{width} h:{height} "
            f"x:{x} y:{y} pts:1 t:0.04 limit:24 crop={width}:{height}:{x}:{y}"
        )

    def test_finds_the_picture_inside_a_pillarboxed_frame(self):
        report = self._report(1440, 1080, x=240)

        assert picture_box([report], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_frame_with_no_bars_is_left_alone(self):
        report = self._report(1920, 1080)

        assert picture_box([report], 1920, 1080) is None

    def test_the_widest_window_wins(self):
        """A window that lands on a fade or a dark shot reads black where there
        is picture. Cropping a scene its own clip does not crop is how a real
        pair stops matching, so a narrow reading never overrides a wide one."""
        dark = self._report(600, 400, x=660, y=340)
        lit = self._report(1440, 1080, x=240)

        assert picture_box([dark, lit, dark], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_video_that_reads_as_nearly_all_black_is_left_alone(self):
        """Below this much picture the likelier story is a dark video, not a
        letterbox — no real one takes half the frame."""
        sliver = int(1080 * MIN_PICTURE_FRACTION) - 20
        report = self._report(1920, sliver, y=(1080 - sliver) // 2)

        assert picture_box([report], 1920, 1080) is None

    def test_nothing_measured_means_nothing_cropped(self):
        assert picture_box(["ffmpeg version 7.1", ""], 1920, 1080) is None

    def test_the_rectangle_is_even_on_every_side(self):
        """Chroma is subsampled, so ffmpeg's crop refuses an odd rectangle."""
        box = picture_box([self._report(1437, 1077, x=241, y=1)], 1920, 1080)

        assert box is not None
        assert not any(value % 2 for value in box)


class TestSampleFrames:
    def _filters(self, monkeypatch, crop) -> str:
        """The filter chain ``sample_frames`` builds for a video cropped *crop*."""
        seen: dict[str, list[str]] = {}

        class _Finished:
            stdout = b""
            stderr = b""

        monkeypatch.setattr(clip_match, "content_crop", lambda video: crop)
        monkeypatch.setattr(
            clip_match.subprocess, "run",
            lambda command, **kwargs: seen.update(command=command) or _Finished(),
        )
        clip_match.sample_frames(Path("scene.mp4"), 8.0)
        command = seen["command"]
        return command[command.index("-vf") + 1]

    def test_the_bars_come_off_before_the_frame_is_scaled_down(self, monkeypatch):
        """Scaling first would squash the bars into the thumbnail, which is the
        whole problem — the picture has to fill the grid the hash reads."""
        assert self._filters(monkeypatch, (1440, 1080, 240, 0)) == (
            f"fps=8.0,crop=1440:1080:240:0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )

    def test_a_video_with_no_bars_is_scaled_whole(self, monkeypatch):
        assert self._filters(monkeypatch, None) == (
            f"fps=8.0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )


class TestAlign:
    def test_bars_stop_a_clip_aligning_with_the_scene_it_came_from(self):
        """Why the crop happens at all. A hash says where things sit in the
        frame, so pillarboxing a scene into a wider one moves its whole picture
        inward and hashes as a different video — a real excerpt then places
        none of itself, which is what a 4:3 scene cut into a 16:9 compilation
        did."""
        rng = np.random.default_rng(21)
        scene = rng.integers(40, 220, size=(60, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)
        excerpt = scene[20:50]
        # The same pixels, squeezed into the middle of a frame of black.
        narrow = np.linspace(0, SAMPLE_WIDTH - 1, SAMPLE_WIDTH - 8).round().astype(int)
        pillarboxed = np.zeros_like(excerpt)
        pillarboxed[:, :, 4:-4] = excerpt[:, :, narrow]

        assert align(frame_hashes(excerpt), frame_hashes(scene), fps=8.0) is not None
        assert align(frame_hashes(pillarboxed), frame_hashes(scene), fps=8.0) is None

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
        scene = lib / "other" / "Nora-Quill_540-izB4YKFa.mp4"

        record(clip, scene, offset=808.25, metadata_root=meta)

        assert read_clip(clip, meta) == {
            "compilation": "Vol1", "index": 9, "performer": "Nora Quill",
            "full_video": str(scene), "scene_offset": 808.25,
        }
        assert json.loads(sidecar.read_text(encoding="utf-8"))["video"] == {"action": "Alpha"}


def _frames(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(count, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)


def _library(tmp_path, files: tuple[tuple[str, int, dict], ...]):
    """*files* — (path under the library root, size, sidecar) — written out.

    Returns the library root, the metadata root beside it, and the entries
    discovery would have made of them.
    """
    lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    entries = []
    for rel, size, payload in files:
        video = lib / rel
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"x" * size)
        sidecar = (meta / rel).with_suffix(".json")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        entries.append(LibraryEntry(video=video, funscript=None, size=size))
    return lib, meta, entries


class TestMatchLibrary:
    def _one_scene_two_clips(self, tmp_path):
        """A performer with one scene (in two versions) and two of her clips."""
        return _library(tmp_path, (
            ("other/Nora-Quill_540-izB4YKFa.mp4", 100, {}),
            ("other/Nora-Quill_540-izB4YKFa_apo8_iris2.mp4", 400, {}),
            ("w/Nora Quill - Nights of Nonsense 8.mp4", 50,
             {"clip": {"compilation": "Vol1", "index": 9, "performer": "Nora Quill"}}),
            ("w/Nora Quill - Scene Three 3.mp4", 50,
             {"clip": {"compilation": "Vol4", "index": 2, "performer": "Nora Quill"}}),
        ))

    def _two_scenes_one_clip(self, tmp_path):
        """Two scenes of a performer whose names share a prefix, and her clip."""
        return _library(tmp_path, (
            ("other/redacted_540-pacI21CK.mp4", 1, {}),
            ("other/redacted Beta Cut 4k 60fps.mp4", 1, {}),
            ("w/redacted - Scene Three 8.mp4", 1,
             {"clip": {"compilation": "Vol7", "index": 4, "performer": "redacted"}}),
        ))

    def _two_cuts_in_one_family(self, tmp_path):
        """Two different cuts saved as "X" and "X (2)", each in its own scene.

        Evolver reads a version family off the name, so the two land in one —
        but they are different footage, cut from two different scenes of the
        same performer.
        """
        clip = {"compilation": "Vol3", "index": 5, "performer": "Nora Quill"}
        return _library(tmp_path, (
            ("other/Nora-Quill_540-izB4YKFa.mp4", 100, {}),
            ("other/Nora-Quill-2_720-QQ7mnbEt.mp4", 100, {}),
            ("w/Nora Quill - Brink.mp4", 60, {"clip": clip, "version": {"group": "Nora Quill - Brink"}}),
            ("w/Nora Quill - Brink (2).mp4", 50, {"clip": clip, "version": {"group": "Nora Quill - Brink"}}),
        ))

    def test_a_family_member_is_measured_rather_than_told(self, tmp_path):
        """The winner's answer used to go to every member of its family. Where a
        family is two different cuts, that filed one under a scene it is not in
        — and handed that scene the wrong cut's funscript."""
        lib, meta, entries = self._two_cuts_in_one_family(tmp_path)
        first, second = _frames(400, seed=21), _frames(400, seed=22)

        def sampler(video, fps):
            if video.name == "Nora-Quill_540-izB4YKFa.mp4":
                return first
            if video.name == "Nora-Quill-2_720-QQ7mnbEt.mp4":
                return second
            if video.name == "Nora Quill - Brink.mp4":
                return first[80:120]
            return second[200:240]

        match_library(entries, meta, fps=8.0, sampler=sampler)

        bigger = read_clip(lib / "w" / "Nora Quill - Brink.mp4", meta)
        smaller = read_clip(lib / "w" / "Nora Quill - Brink (2).mp4", meta)
        assert bigger["full_video"] == str(lib / "other" / "Nora-Quill_540-izB4YKFa.mp4")
        assert bigger["scene_offset"] == 10.0
        assert smaller["full_video"] == str(lib / "other" / "Nora-Quill-2_720-QQ7mnbEt.mp4")
        assert smaller["scene_offset"] == 25.0

    def test_a_member_that_is_another_encode_still_gets_the_answer(self, tmp_path):
        """The family is worth having: a genuine re-encode holds the same
        pictures, aligns in the same scene, and is recorded without being
        decoded twice for the search."""
        lib, meta, entries = _library(tmp_path, (
            ("other/Nora-Quill_540-izB4YKFa.mp4", 100, {}),
            ("w/Nora Quill - Brink.mp4", 60, {"clip": {"compilation": "Vol3", "index": 5,
                                                       "performer": "Nora Quill"},
                                              "version": {"group": "Nora Quill - Brink"}}),
            ("w/Nora Quill - Brink_apo8_iris2.mp4", 50, {"clip": {"compilation": "Vol3", "index": 5,
                                                                  "performer": "Nora Quill"},
                                                         "version": {"group": "Nora Quill - Brink"}}),
        ))
        scene = _frames(400, seed=23)

        def sampler(video, fps):
            return scene if video.parent.name == "other" else scene[80:120]

        match_library(entries, meta, fps=8.0, sampler=sampler)

        for name in ("Nora Quill - Brink.mp4", "Nora Quill - Brink_apo8_iris2.mp4"):
            assert read_clip(lib / "w" / name, meta)["full_video"] == str(
                lib / "other" / "Nora-Quill_540-izB4YKFa.mp4"
            )

    def test_a_wrong_match_an_earlier_run_wrote_is_dropped(self, tmp_path):
        """Self-healing: the sidecars already carry answers handed out on trust,
        and a member proved not to be in that scene must lose the one it has
        rather than keep pointing at it."""
        lib, meta, entries = self._two_cuts_in_one_family(tmp_path)
        scene_one = lib / "other" / "Nora-Quill_540-izB4YKFa.mp4"
        stale = (meta / "w" / "Nora Quill - Brink (2).json")
        payload = json.loads(stale.read_text(encoding="utf-8"))
        payload["clip"].update(full_video=str(scene_one), scene_offset=10.0)
        stale.write_text(json.dumps(payload), encoding="utf-8")
        first, second = _frames(400, seed=21), _frames(400, seed=22)

        def sampler(video, fps):
            if video.name == "Nora-Quill_540-izB4YKFa.mp4":
                return first
            if video.name == "Nora-Quill-2_720-QQ7mnbEt.mp4":
                return second
            if video.name == "Nora Quill - Brink.mp4":
                return first[80:120]
            return second[200:240]

        match_library(entries, meta, fps=8.0, sampler=sampler)

        recorded = read_clip(lib / "w" / "Nora Quill - Brink (2).mp4", meta)
        assert recorded["full_video"] == str(lib / "other" / "Nora-Quill-2_720-QQ7mnbEt.mp4")
        assert recorded["compilation"] == "Vol3"

    def test_records_the_scene_each_clip_was_cut_from(self, tmp_path):
        lib, meta, entries = self._one_scene_two_clips(tmp_path)
        scene_frames = _frames(400, seed=1)

        def sampler(video, fps):
            if video.name.startswith("Nora-Quill"):
                return scene_frames
            if "Nights" in video.name:
                return scene_frames[80:120]
            return _frames(40, seed=2)

        matched = match_library(entries, meta, fps=8.0, sampler=sampler)

        cut_from_it = lib / "w" / "Nora Quill - Nights of Nonsense 8.mp4"
        scene = lib / "other" / "Nora-Quill_540-izB4YKFa.mp4"
        assert list(matched) == [scene]
        assert matched[scene].clip == cut_from_it
        assert read_clip(cut_from_it, meta)["scene_offset"] == 10.0
        assert read_clip(cut_from_it, meta)["full_video"] == str(scene)
        assert "full_video" not in read_clip(lib / "w" / "Nora Quill - Scene Three 3.mp4", meta)

    def test_decodes_the_cheapest_version_of_a_scene(self, tmp_path):
        """Upscales cost minutes where the original costs seconds, and they hold
        the same pictures, so only the smallest file of a family is ever read."""
        _, meta, entries = self._one_scene_two_clips(tmp_path)
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
        lib, meta, entries = self._two_scenes_one_clip(tmp_path)
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

    def test_separates_two_scenes_whose_names_share_a_prefix(self, tmp_path):
        """Two scenes of one performer can share a name prefix without being the
        same video — "redacted_540-hash" and "redacted Beta Cut 4k". Folding them
        would decode one and leave the other unmatchable, so a cut is only
        another's version when the whole reduced title agrees, not its start."""
        _, meta, entries = self._two_scenes_one_clip(tmp_path)
        scenes = []

        def sampler(video, fps):
            if video.parent.name == "other":
                scenes.append(video)
            return _frames(4, seed=5)

        match_library(entries, meta, fps=8.0, sampler=sampler)

        assert len(scenes) == 2

    def test_matches_a_scene_bucketed_under_a_shared_version_group(self, tmp_path):
        """Evolver's version group is not always one video — it buckets by a
        title read out of the name, so unrelated scenes of a performer land in
        one group. Read as a family, the biggest member's name is what the
        candidates are gated on and the smallest member's frames are what gets
        searched, which leaves the clip of every other scene in the bucket
        unmatchable however exactly its frames align."""
        lib, meta, entries = _library(tmp_path, (
            ("other/Jane Doe_iris2.mp4", 900, {"version": {"group": "Jane Doe"}}),
            ("other/Jane-Doe-&-Ada-Roe-b4t7k1qz-old_iris2.mp4", 500,
             {"version": {"group": "Jane Doe"}}),
            ("other/Jane Doe - Cut to Length.mp4", 100, {"version": {"group": "Jane Doe"}}),
            ("w/Jane Doe, Ada Roe - Load Bearing 2.mp4", 50,
             {"clip": {"compilation": "Vol3", "index": 6, "performer": "Jane Doe, Ada Roe"}}),
        ))
        two_performers = _frames(400, seed=11)

        def sampler(video, fps):
            if video.name.startswith("Jane-Doe-&-Ada-Roe"):
                return two_performers
            if video.parent.name == "w":
                return two_performers[80:120]
            return _frames(40, seed=12)

        matched = match_library(entries, meta, fps=8.0, sampler=sampler)

        scene = lib / "other" / "Jane-Doe-&-Ada-Roe-b4t7k1qz-old_iris2.mp4"
        clip = lib / "w" / "Jane Doe, Ada Roe - Load Bearing 2.mp4"
        assert list(matched) == [scene]
        assert matched[scene].clip == clip
        assert read_clip(clip, meta)["full_video"] == str(scene)
        assert read_clip(clip, meta)["scene_offset"] == 10.0


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
