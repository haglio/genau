from __future__ import annotations

import json
from pathlib import Path

from nau.clip_nav import ClipNav, read_clip


def _sidecar(lib: Path, meta: Path, rel: str, payload: dict) -> Path:
    v = lib / rel
    v.parent.mkdir(parents=True, exist_ok=True)
    v.write_bytes(b"x")
    side = (meta / v.relative_to(lib)).with_suffix(".json")
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps(payload), encoding="utf-8")
    return v


def _clip(lib, meta, rel, comp, index, source, performer):
    return _sidecar(lib, meta, rel, {
        "video": {"action": "Alpha"},
        "clip": {"compilation": comp, "index": index, "source": source, "performer": performer},
    })


class TestReadClip:
    def test_reads_clip_field(self, tmp_path):
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        v = _clip(lib, meta, "w/Kim Lee - POV Scene 2.mp4", "Vol6", 9,
                  "POV Scene 2", "Kim Lee")
        c = read_clip(v, meta)
        assert c["compilation"] == "Vol6"
        assert c["index"] == 9
        assert c["performer"] == "Kim Lee"

    def test_missing_sidecar_is_none(self, tmp_path):
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        (lib / "w").mkdir(parents=True)
        v = lib / "w" / "x.mp4"
        v.write_bytes(b"x")
        assert read_clip(v, meta) is None

    def test_version_only_sidecar_is_none(self, tmp_path):
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        v = _sidecar(lib, meta, "w/y.mp4", {"version": {"group": "w/y"}})
        assert read_clip(v, meta) is None


class TestClipNav:
    def _nav(self, tmp_path):
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clips = [
            _clip(lib, meta, "w/Kim Lee - POV Scene 2.mp4", "Vol6", 9, "POV Scene 2", "Kim Lee"),
            _clip(lib, meta, "w/Jane Doe - Pound Region A 2.mp4", "Vol6", 1, "Pound Region A 2", "Jane Doe"),
            _clip(lib, meta, "w/Ada Roe - POV Scene 2.mp4", "Vol6", 7, "POV Scene 2", "Ada Roe"),
            _clip(lib, meta, "w/Kylee King - Taylor Rain.mp4", "Vol10", 1, "Taylor Rain's Offroad Adventure", "Kylee King"),
        ]
        full = _sidecar(lib, meta, "other/POV Scene 2 - Kim Lee 1080p.mp4", {})
        nav = ClipNav.build([*clips, full], meta)
        return nav, clips, full

    def test_is_clip(self, tmp_path):
        nav, clips, full = self._nav(tmp_path)
        assert nav.is_clip(clips[0]) is True
        assert nav.is_clip(full) is False

    def test_compilation_of_names_the_volume_a_clip_came_from(self, tmp_path):
        """Nau's HUD says which compilation is holding the playlist, so the title
        has to be reachable from the clip that put it there."""
        nav, clips, full = self._nav(tmp_path)

        assert nav.compilation_of(clips[0]) == "Vol6"
        assert nav.compilation_of(full) == ""

    def test_compilation_playlist_orders_by_index(self, tmp_path):
        nav, clips, _ = self._nav(tmp_path)
        # from Kim Lee (Vol6 #9): siblings Amia(#1), Avy(#7), Charley(#9)
        order = nav.compilation_playlist(clips[0])
        names = [p.stem.split(" - ")[0] for p in order]
        assert names == ["Jane Doe", "Ada Roe", "Kim Lee"]

    def test_compilation_playlist_excludes_other_volumes(self, tmp_path):
        nav, clips, _ = self._nav(tmp_path)
        order = nav.compilation_playlist(clips[1])  # Amia, Vol6
        assert all("Vol10" not in str(p) for p in order)
        assert len(order) == 3

    def test_compilation_playlist_empty_for_non_clip(self, tmp_path):
        nav, _, full = self._nav(tmp_path)
        assert nav.compilation_playlist(full) == []

    def test_full_vid_of_matches_source_and_performer(self, tmp_path):
        nav, clips, full = self._nav(tmp_path)
        # Kim Lee clip -> the "POV Scene 2 - Kim Lee" full scene
        assert nav.full_vid_of(clips[0]) == full

    def test_full_vid_of_none_when_absent(self, tmp_path):
        nav, clips, _ = self._nav(tmp_path)
        # Jane Doe / Pound Region A 2 has no matching full scene in the library
        assert nav.full_vid_of(clips[1]) is None

    def test_clip_of_reverse_matches(self, tmp_path):
        nav, clips, full = self._nav(tmp_path)
        assert nav.clip_of(full) == clips[0]

    def test_clip_of_ignores_a_performer_with_several_scenes(self, tmp_path):
        """A title like "Asa Akira To the Limit" must not claim every Asa Akira
        file: with several of her scenes present, which one it came from is
        unknowable, so neither direction may guess. (With exactly one it is not
        a guess — see the redacted case.)"""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = _clip(lib, meta, "w/Asa Akira - Asa Akira To the Limit.mp4", "Vol1", 11,
                     "Asa Akira To the Limit", "Asa Akira")
        stranger = _sidecar(lib, meta, "other/Asa Akira - 9934197-720p.mp4", {})
        other = _sidecar(lib, meta, "other/redacted_1080-jx3sHGzf.mp4", {})
        nav = ClipNav.build([clip, stranger, other], meta)
        assert nav.clip_of(stranger) is None
        assert nav.full_vid_of(clip) is None

    def test_compilation_playlist_keeps_one_slot_per_scene(self, tmp_path):
        """An upscaled variant carries the same clip object; the playlist keeps the
        larger file once, not both versions of the scene."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        original = _clip(lib, meta, "w/Jane Doe - Pound Region A 2.mp4", "Vol6", 1, "Pound Region A 2", "Jane Doe")
        upscaled = _clip(lib, meta, "w/Jane Doe - Pound Region A 2_apo8_iris2.mp4", "Vol6", 1, "Pound Region A 2", "Jane Doe")
        upscaled.write_bytes(b"x" * 500)  # the enhanced file is the bigger one
        other = _clip(lib, meta, "w/Alexis Silver - POV 1.mp4", "Vol6", 2, "POV Scene 1", "Alexis Silver")
        nav = ClipNav.build([original, upscaled, other], meta)

        playlist = nav.compilation_playlist(original)

        assert playlist == [upscaled, other]

    def test_full_vid_resolves_on_performer_when_they_have_one_scene(self, tmp_path):
        """Most library files are named performer + resolution + hash, with no
        movie title at all — so a source-word match can never fire. One scene for
        that performer is unambiguous, so it resolves."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = _clip(lib, meta, "w/redacted - redacted Overload 3.mp4", "Vol4", 4,
                     "redacted Overload 3", "redacted")
        scene = _sidecar(lib, meta, "other/redacted_540-fDn1L7uT.mp4", {})
        nav = ClipNav.build([clip, scene], meta)

        assert nav.full_vid_of(clip) == scene

    def test_full_vid_stays_ambiguous_with_several_scenes_for_the_performer(self, tmp_path):
        """With several scenes by that performer there is no way to tell which one
        the clip came from, so it must not guess."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = _clip(lib, meta, "w/Asa Akira - Asa Akira To the Limit.mp4", "Vol1", 11,
                     "Asa Akira To the Limit", "Asa Akira")
        _sidecar(lib, meta, "other/redacted_540-EhWGJW62.mp4", {})
        _sidecar(lib, meta, "other/redacted_1080-jx3sHGzf.mp4", {})
        nav = ClipNav.build([clip, *[lib / "other" / n for n in
                                     ("redacted_540-EhWGJW62.mp4", "redacted_1080-jx3sHGzf.mp4")]], meta)

        assert nav.full_vid_of(clip) is None

    def test_re_encodes_of_one_scene_are_not_ambiguous(self, tmp_path):
        """X.mp4 and X_iris2.mp4 are the same scene; the bigger one wins."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = _clip(lib, meta, "w/redacted - redacted Overload 3.mp4", "Vol4", 4,
                     "redacted Overload 3", "redacted")
        plain = _sidecar(lib, meta, "other/redacted_540-fDn1L7uT.mp4", {})
        upscaled = _sidecar(lib, meta, "other/redacted_540-fDn1L7uT_iris2.mp4", {})
        upscaled.write_bytes(b"x" * 400)
        nav = ClipNav.build([clip, plain, upscaled], meta)

        assert nav.full_vid_of(clip) == upscaled

    def test_money_shot_never_returns_the_file_you_are_on(self, tmp_path):
        """A clip matches its own name; returning it just replayed the video."""
        lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
        clip = _clip(lib, meta, "w/Kim Lee - POV Scene 2.mp4", "Vol6", 9,
                     "POV Scene 2", "Kim Lee")
        nav = ClipNav.build([clip], meta)

        assert nav.clip_of(clip) is None

    def test_clip_of_none_for_unrelated(self, tmp_path):
        nav, clips, full = self._nav(tmp_path)
        lib = tmp_path / "videos" / "videos"
        stranger = _sidecar(lib, tmp_path / "videos" / "metadata", "other/Some Random Movie.mp4", {})
        nav2 = ClipNav.build([*clips, full, stranger], tmp_path / "videos" / "metadata")
        assert nav2.clip_of(stranger) is None


def test_a_scene_and_its_apo8_iris2_upscale_are_one_scene(tmp_path):
    """Evolver's own output suffix was not in the quality-token list, so a scene
    and its upscale counted as two candidates and the match declined."""
    lib, meta = tmp_path / "videos" / "videos", tmp_path / "videos" / "metadata"
    clip = _clip(lib, meta, "w/Emy Reyes - Angels of Debauchery 8.mp4", "Vol1", 9,
                 "Angels of Debauchery 8", "Emy Reyes")
    plain = _sidecar(lib, meta, "other/Emy-Reyes_540-izB4YKFa.mp4", {})
    upscale = _sidecar(lib, meta, "other/Emy-Reyes_540-izB4YKFa_apo8_iris2.mp4", {})
    upscale.write_bytes(b"x" * 400)
    nav = ClipNav.build([clip, plain, upscale], meta)

    assert nav.full_vid_of(clip) == upscale
    assert nav.clip_of(plain) == clip
