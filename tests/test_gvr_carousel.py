"""The clips a session can show, and which frame of the one on screen.

Both of these lived in the frame loop as locals rebound through a nested
closure, so neither could be exercised without an OpenXR runtime and a headset.
Neither had a test.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from genau_vr.carousel import ClipCarousel


def _frames(count: int) -> list[np.ndarray]:
    """One tiny frame per index, each one telling you which index it is."""
    return [np.full((2, 2, 3), i, dtype=np.uint8) for i in range(count)]


class FakeAudio:
    def __init__(self) -> None:
        self.loaded: list[Path] = []

    def load_for_clip(self, path: Path) -> None:
        self.loaded.append(path)


def _carousel(names=("alpha.mp4", "beta.mp4", "gamma.mp4"), frames=4, **over):
    audio = over.pop("audio", FakeAudio())
    decoded = over.pop("decode", lambda _path: _frames(frames))
    return ClipCarousel(
        [Path(name) for name in names], _frames(frames),
        audio=audio, decode=decoded, **over,
    ), audio


class TestSteppingAlongTheClips:
    def test_it_moves_to_the_next_one_and_decodes_it(self):
        carousel, _audio = _carousel()

        assert carousel.step(1) is True
        assert carousel.current_path == Path("beta.mp4")

    def test_it_wraps_around_in_both_directions(self):
        carousel, _audio = _carousel()

        carousel.step(-1)
        assert carousel.current_path == Path("gamma.mp4")

        carousel.step(1)
        assert carousel.current_path == Path("alpha.mp4")

    def test_the_sound_follows_the_picture(self):
        carousel, audio = _carousel()

        carousel.step(1)

        assert audio.loaded == [Path("beta.mp4")]

    def test_a_session_with_one_clip_steps_nowhere(self):
        """Reloading the one clip would stop the picture and restart the sound
        for no move."""
        carousel, audio = _carousel(names=("alpha.mp4",))

        assert carousel.step(1) is False
        assert audio.loaded == []
        assert carousel.current_path == Path("alpha.mp4")

    def test_nothing_is_on_screen_until_a_frame_is_chosen(self):
        """Not the same as frame zero being up: a new clip must upload its first
        frame, and a `0` here would have it skipped as already showing."""
        carousel, _audio = _carousel()
        carousel.frame_for_phase(0.0, auto_active=True)

        carousel.step(1)

        assert carousel.showing == -1

    def test_a_shorter_clip_does_not_leave_the_old_frame_count_behind(self):
        """Stepped to a clip with fewer frames, a stale count would index past
        the end of the new one."""
        carousel, _audio = _carousel(frames=8, decode=lambda _path: _frames(2))

        carousel.step(1)
        chosen = carousel.frame_for_phase(0.99, auto_active=True)

        assert chosen is not None
        assert len(carousel.frames) == 2


class TestWhichFrameGoesUp:
    def test_the_first_ask_always_returns_one(self):
        carousel, _audio = _carousel()

        assert carousel.frame_for_phase(0.0, auto_active=True) is not None

    def test_asking_twice_at_the_same_phase_returns_nothing_the_second_time(self):
        """Uploading a texture is the most expensive thing in the frame, and a
        paused clip would otherwise pay it every turn."""
        carousel, _audio = _carousel()
        carousel.frame_for_phase(0.0, auto_active=True)

        assert carousel.frame_for_phase(0.0, auto_active=True) is None

    def test_a_phase_that_lands_on_another_frame_returns_it(self):
        carousel, _audio = _carousel(frames=4)
        carousel.frame_for_phase(0.0, auto_active=True)

        chosen = carousel.frame_for_phase(0.5, auto_active=True)

        assert chosen is not None
        assert carousel.showing == 2

    def test_the_frame_returned_is_the_one_at_the_index_it_chose(self):
        carousel, _audio = _carousel(frames=4)

        chosen = carousel.frame_for_phase(0.5, auto_active=True)

        assert chosen is not None
        assert int(chosen[0, 0, 0]) == carousel.showing


def test_the_carousel_opens_on_the_clip_it_was_given(tmp_path):
    frames = _frames(3)
    carousel = ClipCarousel([Path("alpha.mp4"), Path("beta.mp4")], frames)

    assert carousel.current_path == Path("alpha.mp4")
    assert carousel.frames is frames


def test_a_carousel_with_no_sound_still_steps():
    """The mixer is allowed to be unavailable; the picture is not."""
    carousel = ClipCarousel(
        [Path("alpha.mp4"), Path("beta.mp4")], _frames(2),
        decode=lambda _path: _frames(2),
    )

    assert carousel.step(1) is True
