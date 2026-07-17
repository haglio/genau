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

    def test_clip_of_none_for_unrelated(self, tmp_path):
        nav, clips, full = self._nav(tmp_path)
        lib = tmp_path / "videos" / "videos"
        stranger = _sidecar(lib, tmp_path / "videos" / "metadata", "other/Some Random Movie.mp4", {})
        nav2 = ClipNav.build([*clips, full, stranger], tmp_path / "videos" / "metadata")
        assert nav2.clip_of(stranger) is None
