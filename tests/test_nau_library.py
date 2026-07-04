from __future__ import annotations

import random
from pathlib import Path

from nau.library import (
    LibraryEntry,
    VersionGroup,
    canonical_playlist,
    group_versions,
    library_playlist,
    normalize_title,
    select_library,
    version_index_from_groups,
)


def _entry(name: str, size: int, funscript: str | None = None) -> LibraryEntry:
    return LibraryEntry(
        video=Path(name),
        funscript=Path(funscript) if funscript else None,
        size=size,
    )


class TestNormalizeTitle:
    def test_lowercases(self):
        assert normalize_title("Asa-Akira") == "asa akira"

    def test_strips_quality_and_upscaler_tokens(self):
        assert normalize_title("vanessa-leon-redacted-it-dry-upscale-mp4-1080p_60fps") == "redacted redacted it dry"
        assert normalize_title("Lana-Violet-&-Tia-Ling-old_iris2") == "lana violet & tia ling"

    def test_strips_trailing_hash_tokens(self):
        # 6-12 char alnum tokens mixing letters+digits, when trailing.
        assert normalize_title("redacted_540-EhWGJW62") == "redacted"
        assert normalize_title("Lana-Violet-&-Tia-Ling-ix1x4lx5-old_iris2") == "lana violet & tia ling"
        # A trailing hash exposed only after a quality token is stripped.
        assert normalize_title("funscripted_video-0980a34b_topaz") == "funscripted video"


class TestGroupVersions:
    def test_singleton_group(self):
        groups = group_versions([_entry("solo.mp4", 100)])

        assert len(groups) == 1
        assert isinstance(groups[0], VersionGroup)
        assert groups[0].canonical.video == Path("solo.mp4")
        assert groups[0].alternates == []

    def test_largest_file_is_canonical(self):
        small = _entry("Asa-Akira-540.mp4", size=100)
        big = _entry("redacted080p.mp4", size=900)
        mid = _entry("Asa-Akira-720p.mp4", size=400)

        groups = group_versions([small, big, mid])

        assert len(groups) == 1
        assert groups[0].canonical is big
        assert [a.video for a in groups[0].alternates] == [
            Path("Asa-Akira-720p.mp4"),
            Path("Asa-Akira-540.mp4"),
        ]

    def test_distinct_titles_stay_separate(self):
        groups = group_versions([
            _entry("alpha-1080p.mp4", 100),
            _entry("beta-1080p.mp4", 100),
        ])

        assert [g.canonical.video for g in groups] == [
            Path("alpha-1080p.mp4"),
            Path("beta-1080p.mp4"),
        ]

    def test_scripted_and_unscripted_alternate_group_together(self):
        scripted = _entry("Riley-Reid-topaz.mp4", size=500, funscript="Riley-Reid.funscript")
        unscripted = _entry("Riley-Reid-1080p.mp4", size=800)

        groups = group_versions([scripted, unscripted])

        assert len(groups) == 1
        assert groups[0].canonical is unscripted  # larger
        assert groups[0].alternates == [scripted]
        assert groups[0].alternates[0].funscript == Path("Riley-Reid.funscript")



class TestCanonicalPlaylist:
    def test_one_canonical_entry_per_group(self):
        entries = [
            _entry("Asa-Akira-540.mp4", 100),
            _entry("redacted080p.mp4", 900),  # canonical of its group
            _entry("Riley-Reid-720p.mp4", 200),  # sole member
        ]

        playlist = canonical_playlist(entries, random.Random(0))

        videos = {e.video for e in playlist}
        assert videos == {Path("redacted080p.mp4"), Path("Riley-Reid-720p.mp4")}
        assert len(playlist) == 2

    def test_deterministic_given_seeded_rng(self):
        entries = [_entry(f"vid-{i}-1080p.mp4", 100) for i in range(8)]

        first = canonical_playlist(entries, random.Random(42))
        second = canonical_playlist(entries, random.Random(42))

        assert [e.video for e in first] == [e.video for e in second]

    def test_returns_library_entries(self):
        playlist = canonical_playlist([_entry("solo-1080p.mp4", 100)], random.Random(1))

        assert isinstance(playlist[0], LibraryEntry)


class TestSelectLibrary:
    def _durations(self, mapping):
        return {Path(k): v for k, v in mapping.items()}

    def test_full_length_mode_keeps_only_long_videos(self):
        entries = [
            _entry("long-1080p.mp4", 100),
            _entry("clip-1080p.mp4", 100),
        ]
        durations = self._durations({"long-1080p.mp4": 300.0, "clip-1080p.mp4": 12.0})

        result = select_library(entries, mode="full", durations=durations, clips=[])

        assert [e.video for e in result] == [Path("long-1080p.mp4")]

    def test_shorts_mode_keeps_only_short_videos(self):
        entries = [
            _entry("long-1080p.mp4", 100),
            _entry("clip-1080p.mp4", 100),
        ]
        durations = self._durations({"long-1080p.mp4": 300.0, "clip-1080p.mp4": 12.0})

        result = select_library(entries, mode="shorts", durations=durations, clips=[])

        assert [e.video for e in result] == [Path("clip-1080p.mp4")]

    def test_boundary_60s_is_short(self):
        entries = [_entry("exactly-60-1080p.mp4", 100)]
        durations = self._durations({"exactly-60-1080p.mp4": 60.0})

        assert select_library(entries, mode="shorts", durations=durations, clips=[])
        assert not select_library(entries, mode="full", durations=durations, clips=[])

    def test_long_compilation_is_not_a_short(self):
        # Duration-driven only: a "compilation" name doesn't make it short.
        entries = [_entry("mega-compilation-1080p.mp4", 100)]
        durations = self._durations({"mega-compilation-1080p.mp4": 1800.0})

        assert not select_library(entries, mode="shorts", durations=durations, clips=[])
        assert select_library(entries, mode="full", durations=durations, clips=[])

    def test_shorts_mode_includes_clips(self):
        entries = [_entry("long-1080p.mp4", 100)]
        clips = [_entry("saved-clip.mp4", 50)]
        durations = self._durations({"long-1080p.mp4": 300.0})

        result = select_library(entries, mode="shorts", durations=durations, clips=clips)

        assert Path("saved-clip.mp4") in {e.video for e in result}

    def test_full_length_mode_excludes_clips(self):
        entries = [_entry("long-1080p.mp4", 100)]
        clips = [_entry("saved-clip.mp4", 50)]
        durations = self._durations({"long-1080p.mp4": 300.0})

        result = select_library(entries, mode="full", durations=durations, clips=clips)

        assert Path("saved-clip.mp4") not in {e.video for e in result}

    def test_empty_clips_shorts_mode_is_duration_only(self):
        entries = [_entry("clip-1080p.mp4", 100)]
        durations = self._durations({"clip-1080p.mp4": 10.0})

        result = select_library(entries, mode="shorts", durations=durations, clips=[])

        assert [e.video for e in result] == [Path("clip-1080p.mp4")]

    def test_missing_duration_excluded_from_length_filter(self):
        # An unprobed video (no duration) can't be classified; leave it out.
        entries = [_entry("unknown-1080p.mp4", 100)]

        assert select_library(entries, mode="full", durations={}, clips=[]) == []
        assert select_library(entries, mode="shorts", durations={}, clips=[]) == []

    def test_applies_version_dedup(self):
        entries = [
            _entry("Asa-540.mp4", 100),
            _entry("Asa-1080p.mp4", 900),
        ]
        durations = self._durations({"Asa-540.mp4": 300.0, "Asa-1080p.mp4": 300.0})

        result = select_library(entries, mode="full", durations=durations, clips=[])

        assert [e.video for e in result] == [Path("Asa-1080p.mp4")]


class TestLibraryPlaylist:
    def _durations(self, mapping):
        return {Path(k): v for k, v in mapping.items()}

    def test_full_length_pairs_are_deduped_and_shuffled(self):
        entries = [
            _entry("Asa-540.mp4", 100, funscript="Asa.funscript"),
            _entry("Asa-1080p.mp4", 900),  # canonical (bigger), no funscript
            _entry("Riley-720p.mp4", 200, funscript="Riley.funscript"),
        ]
        durations = self._durations({
            "Asa-540.mp4": 300.0, "Asa-1080p.mp4": 300.0, "Riley-720p.mp4": 300.0,
        })

        pairs = library_playlist(
            entries, mode="full", durations=durations, clips=[],
            rng=random.Random(0),
        )

        # One entry per title; canonical (largest) chosen; correct pairing.
        as_dict = dict(pairs)
        assert set(as_dict) == {Path("Asa-1080p.mp4"), Path("Riley-720p.mp4")}
        assert as_dict[Path("Asa-1080p.mp4")] is None
        assert as_dict[Path("Riley-720p.mp4")] == Path("Riley.funscript")

    def test_returns_path_tuples(self):
        entries = [_entry("solo-1080p.mp4", 100, funscript="solo.funscript")]
        durations = self._durations({"solo-1080p.mp4": 300.0})

        pairs = library_playlist(
            entries, mode="full", durations=durations, clips=[],
            rng=random.Random(0),
        )

        assert pairs == [(Path("solo-1080p.mp4"), Path("solo.funscript"))]

    def test_deterministic_given_seed(self):
        entries = [_entry(f"v{i}-1080p.mp4", 100) for i in range(6)]
        durations = self._durations({f"v{i}-1080p.mp4": 300.0 for i in range(6)})

        a = library_playlist(entries, mode="full", durations=durations, clips=[], rng=random.Random(3))
        b = library_playlist(entries, mode="full", durations=durations, clips=[], rng=random.Random(3))
        assert a == b


class TestVersionIndex:
    def test_maps_every_member_to_ordered_group_pairs(self):
        big = _entry("Asa-1080p.mp4", 900)
        mid = _entry("Asa-720p.mp4", 400, funscript="Asa.funscript")
        solo = _entry("Riley-1080p.mp4", 100)
        groups = group_versions([mid, big, solo])

        index = version_index_from_groups(groups)

        asa_pairs = [(Path("Asa-1080p.mp4"), None), (Path("Asa-720p.mp4"), Path("Asa.funscript"))]
        assert index[Path("Asa-1080p.mp4")] == asa_pairs
        assert index[Path("Asa-720p.mp4")] == asa_pairs
        assert index[Path("Riley-1080p.mp4")] == [(Path("Riley-1080p.mp4"), None)]

    def test_singleton_maps_to_itself_only(self):
        groups = group_versions([_entry("solo-1080p.mp4", 100)])

        index = version_index_from_groups(groups)

        assert index == {Path("solo-1080p.mp4"): [(Path("solo-1080p.mp4"), None)]}
