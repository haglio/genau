from __future__ import annotations

import random
from pathlib import Path

from nau.library import (
    MIXED,
    LibraryEntry,
    VersionGroup,
    canonical_playlist,
    collapse_playlist_versions,
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
        assert normalize_title("Jane-Doe") == "jane doe"

    def test_strips_quality_and_upscaler_tokens(self):
        assert normalize_title("Jane Doe-redacted-it-dry-upscale-mp4-1080p_60fps") == "redacted redacted it dry"
        assert normalize_title("Jane-Doe-&-John-Roe-old_iris2") == "jane doe & john roe"

    def test_strips_trailing_hash_tokens(self):
        # 6-12 char alnum tokens mixing letters+digits, when trailing.
        assert normalize_title("redacted_540-EhWGJW62") == "redacted"
        assert normalize_title("Jane-Doe-&-John-Roe-ix1x4lx5-old_iris2") == "jane doe & john roe"
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
        small = _entry("Jane-Doe-540.mp4", size=100)
        big = _entry("redacted080p.mp4", size=900)
        mid = _entry("Jane-Doe-720p.mp4", size=400)

        groups = group_versions([small, big, mid])

        assert len(groups) == 1
        assert groups[0].canonical is big
        assert [a.video for a in groups[0].alternates] == [
            Path("Jane-Doe-720p.mp4"),
            Path("Jane-Doe-540.mp4"),
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
        scripted = _entry("John-Roe-topaz.mp4", size=500, funscript="John-Roe.funscript")
        unscripted = _entry("John-Roe-1080p.mp4", size=800)

        groups = group_versions([scripted, unscripted])

        assert len(groups) == 1
        assert groups[0].canonical is unscripted  # larger
        assert groups[0].alternates == [scripted]
        assert groups[0].alternates[0].funscript == Path("John-Roe.funscript")

    def test_upscale_with_appended_tag_folds_into_original(self):
        # The real-world miss: the upscale is the original's name plus an
        # appended tag, and the original's trailing hash is stripped while the
        # upscale keeps it mid-name — so exact-title matching split them. A
        # token-wise prefix match ("richard roe" begins the upscale) folds them.
        original = _entry("Richard-Roe-lA0JUsAd.mp4", size=166)
        upscale = _entry("Richard-Roe-lA0JUsAd_3_apf2_iris2.mp4", size=6035)

        groups = group_versions([original, upscale])

        assert len(groups) == 1
        assert groups[0].canonical is upscale  # larger
        assert groups[0].alternates == [original]

    def test_numbered_scenes_with_shared_prefix_stay_separate(self):
        # Same performer, different scene index — NOT versions of each other,
        # even though they share the first two tokens.
        one = _entry("Mary-Roe-1_1080-rzGPIJrZ.mp4", size=1043)
        two = _entry("Mary-Roe-2_720-ZByXAJ6K.mp4", size=347)

        groups = group_versions([one, two])

        assert len(groups) == 2

    def test_upscales_of_different_numbered_scenes_form_separate_pairs(self):
        # Several short scenes, each with an appended-tag upscale, must fold
        # into one pair per scene — not a single over-grouped blob (which the
        # old first-two-tokens + duration heuristic produced for same-length
        # clips of one performer).
        entries = []
        for n in (1, 2, 3):
            entries.append(_entry(f"clip-{n}.mp4", size=10))
            entries.append(_entry(f"clip-{n}_apo8_iris2.mp4", size=400))

        groups = group_versions(entries)

        assert len(groups) == 3
        assert all(len(g.members) == 2 for g in groups)



class TestCanonicalPlaylist:
    def test_one_canonical_entry_per_group(self):
        entries = [
            _entry("Jane-Doe-540.mp4", 100),
            _entry("redacted080p.mp4", 900),  # canonical of its group
            _entry("John-Roe-720p.mp4", 200),  # sole member
        ]

        playlist = canonical_playlist(entries, random.Random(0))

        videos = {e.video for e in playlist}
        assert videos == {Path("redacted080p.mp4"), Path("John-Roe-720p.mp4")}
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

    def test_mixed_mode_keeps_everything(self):
        """The mode the player opens in: no length filter at all, which is what
        Fun Time's own playlist has always been."""
        entries = [_entry("long-1080p.mp4", 100), _entry("clip-1080p.mp4", 100)]
        durations = self._durations({"long-1080p.mp4": 300.0, "clip-1080p.mp4": 12.0})
        saved = [_entry("saved-clip.mp4", 100)]

        result = select_library(entries, mode=MIXED, durations=durations, clips=saved)

        assert [e.video for e in result] == [
            Path("long-1080p.mp4"), Path("clip-1080p.mp4"), Path("saved-clip.mp4"),
        ]

    def test_mixed_mode_keeps_a_video_whose_duration_never_probed(self):
        """Length modes drop what they cannot classify; mixed classifies nothing,
        so an unprobed video is still playable."""
        entries = [_entry("unprobed-1080p.mp4", 100)]

        assert select_library(entries, mode=MIXED, durations={}, clips=[])
        assert not select_library(entries, mode="shorts", durations={}, clips=[])
        assert not select_library(entries, mode="full", durations={}, clips=[])

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
            _entry("Jane-540.mp4", 100),
            _entry("Jane-1080p.mp4", 900),
        ]
        durations = self._durations({"Jane-540.mp4": 300.0, "Jane-1080p.mp4": 300.0})

        result = select_library(entries, mode="full", durations=durations, clips=[])

        assert [e.video for e in result] == [Path("Jane-1080p.mp4")]


class TestLibraryPlaylist:
    def _durations(self, mapping):
        return {Path(k): v for k, v in mapping.items()}

    def test_full_length_pairs_are_deduped_and_shuffled(self):
        entries = [
            _entry("Jane-540.mp4", 100, funscript="Jane.funscript"),
            _entry("Jane-1080p.mp4", 900),  # canonical (bigger), no funscript
            _entry("John-720p.mp4", 200, funscript="John.funscript"),
        ]
        durations = self._durations({
            "Jane-540.mp4": 300.0, "Jane-1080p.mp4": 300.0, "John-720p.mp4": 300.0,
        })

        pairs = library_playlist(
            entries, mode="full", durations=durations, clips=[],
            rng=random.Random(0),
        )

        # One entry per title; canonical (largest) chosen; correct pairing.
        as_dict = dict(pairs)
        assert set(as_dict) == {Path("Jane-1080p.mp4"), Path("John-720p.mp4")}
        assert as_dict[Path("Jane-1080p.mp4")] is None
        assert as_dict[Path("John-720p.mp4")] == Path("John.funscript")

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
        big = _entry("Jane-1080p.mp4", 900)
        mid = _entry("Jane-720p.mp4", 400, funscript="Jane.funscript")
        solo = _entry("John-1080p.mp4", 100)
        groups = group_versions([mid, big, solo])

        index = version_index_from_groups(groups)

        jane_pairs = [(Path("Jane-1080p.mp4"), None), (Path("Jane-720p.mp4"), Path("Jane.funscript"))]
        assert index[Path("Jane-1080p.mp4")] == jane_pairs
        assert index[Path("Jane-720p.mp4")] == jane_pairs
        assert index[Path("John-1080p.mp4")] == [(Path("John-1080p.mp4"), None)]

    def test_singleton_maps_to_itself_only(self):
        groups = group_versions([_entry("solo-1080p.mp4", 100)])

        index = version_index_from_groups(groups)

        assert index == {Path("solo-1080p.mp4"): [(Path("solo-1080p.mp4"), None)]}


class TestScriptedOnly:
    def test_full_length_scripted_only_drops_unscripted(self):
        from nau.library import select_library, FULL
        scripted = _entry("Amy-Long-topaz.mp4", size=900, funscript="Amy-Long.funscript")
        unscripted = _entry("Bea-Long-1080p.mp4", size=900)
        durations = {scripted.video: 300.0, unscripted.video: 300.0}

        kept = select_library(
            [scripted, unscripted], mode=FULL, durations=durations, clips=[],
            scripted_only=True,
        )

        assert [e.video for e in kept] == [scripted.video]

    def test_scripted_only_still_includes_clips_in_shorts(self):
        from nau.library import select_library, SHORTS
        scripted_short = _entry("Cee-topaz.mp4", size=100, funscript="Cee.funscript")
        unscripted_short = _entry("Dee-1080p.mp4", size=100)
        clip = _entry("saved-clip.mp4", size=50)
        durations = {scripted_short.video: 30.0, unscripted_short.video: 30.0}

        kept = select_library(
            [scripted_short, unscripted_short], mode=SHORTS, durations=durations,
            clips=[clip], scripted_only=True,
        )
        vids = {e.video for e in kept}

        assert scripted_short.video in vids       # scripted short kept
        assert unscripted_short.video not in vids  # unscripted short dropped
        assert clip.video in vids                  # clips always included

    def test_default_keeps_unscripted(self):
        from nau.library import select_library, FULL
        unscripted = _entry("Eff-1080p.mp4", size=900)
        kept = select_library(
            [unscripted], mode=FULL, durations={unscripted.video: 300.0}, clips=[],
        )
        assert [e.video for e in kept] == [unscripted.video]


class TestRealWorldNameGrouping:
    def test_original_with_hash_and_appended_upscale_fold(self):
        # The upscale is the original's name — trailing hash and all — plus an
        # appended pipeline tag, so the original's normalized title is a clean
        # token prefix of the upscale's. This is the dominant real-world shape.
        original = _entry("redacted_560-XmbgwUF4.mp4", size=289_000_000)
        upscale = _entry("redacted_560-XmbgwUF4_apo8_iris2.mp4", size=31_822_000_000)

        groups = group_versions([original, upscale])

        assert len(groups) == 1
        assert groups[0].canonical is upscale  # larger file
        assert groups[0].alternates == [original]

    def test_different_scene_names_stay_separate(self):
        a = _entry("Jane Doe-scene-a.mp4", size=100)
        b = _entry("Jane Doe-scene-b-1080p.mp4", size=100)

        groups = group_versions([a, b])

        assert len(groups) == 2


class TestCollapsePlaylistVersions:
    def _index(self, entries):
        return version_index_from_groups(group_versions(entries))

    def test_keeps_one_slot_per_group_at_first_seen_position(self):
        # A rotation listing both original and upscale collapses to the larger,
        # at the first-seen position, dropping the later duplicate.
        index = self._index([_entry("Richard.mp4", 166), _entry("Richard_topaz.mp4", 6035)])
        pairs = [
            (Path("Richard.mp4"), None),
            (Path("Other.mp4"), None),
            (Path("Richard_topaz.mp4"), None),
        ]

        result = collapse_playlist_versions(pairs, index)

        assert result == [(Path("Richard_topaz.mp4"), None), (Path("Other.mp4"), None)]

    def test_keeps_the_kept_members_funscript(self):
        index = self._index([_entry("Richard.mp4", 166), _entry("Richard_topaz.mp4", 6035)])
        pairs = [
            (Path("Richard_topaz.mp4"), Path("Richard_topaz.funscript")),
            (Path("Richard.mp4"), Path("Richard.funscript")),
        ]

        result = collapse_playlist_versions(pairs, index)

        assert result == [(Path("Richard_topaz.mp4"), Path("Richard_topaz.funscript"))]

    def test_keeps_only_present_member_when_larger_absent(self):
        # F-mode may have filtered the upscale out; keep whatever version is here.
        index = self._index([_entry("Richard.mp4", 166), _entry("Richard_topaz.mp4", 6035)])
        pairs = [(Path("Richard.mp4"), Path("Richard.funscript"))]

        result = collapse_playlist_versions(pairs, index)

        assert result == [(Path("Richard.mp4"), Path("Richard.funscript"))]

    def test_video_absent_from_index_passes_through(self):
        result = collapse_playlist_versions([(Path("mystery.mp4"), None)], {})

        assert result == [(Path("mystery.mp4"), None)]


class TestGroupVersionsByRecordedId:
    def test_recorded_id_folds_clips_names_never_would(self):
        a = _entry("Totally-Different-A.mp4", 100)
        b = _entry("unrelated_name_b.mp4", 900)
        ids = {a.video: "fam1", b.video: "fam1"}

        groups = group_versions([a, b], lambda v: ids.get(v))

        assert len(groups) == 1
        assert groups[0].canonical is b  # larger
        assert groups[0].alternates == [a]

    def test_clips_without_a_recorded_id_fall_back_to_name_grouping(self):
        rec_a = _entry("scene.mp4", 100)
        rec_b = _entry("other.mp4", 100)
        richard = _entry("Richard.mp4", 50)
        richard_up = _entry("Richard_topaz.mp4", 800)
        ids = {rec_a.video: "f", rec_b.video: "f"}  # the Richards have no sidecar

        groups = group_versions([rec_a, rec_b, richard, richard_up], lambda v: ids.get(v))

        member_sets = [sorted(str(m.video) for m in g.members) for g in groups]
        assert sorted([str(rec_a.video), str(rec_b.video)]) in member_sets
        assert sorted([str(richard.video), str(richard_up.video)]) in member_sets
        assert len(groups) == 2
