"""Tests for genau_vr.app startup error handling."""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from genau_vr.vr_runtime import Probe, Readiness


@pytest.fixture(autouse=True)
def _do_not_name_the_interpreter(monkeypatch):
    """Keep ``main()`` from preparing the launcher on the machine running this.

    ``_name_this_process`` copies the running interpreter to a role-named
    sibling and stamps an icon onto it — real work on Windows, where these tests
    run for real, done five times over by the five cases that call ``main``.  It
    swallows its own exceptions, so it costs a file and a copy rather than a red
    test, which is exactly why nothing noticed.
    """
    import genau_vr.app

    monkeypatch.setattr(genau_vr.app, "_name_this_process", lambda: None)


def _ready() -> Probe:
    return Probe(Readiness.READY)


def test_main_shows_error_popup_on_vr_init_failure():
    """When VRSession() raises, main should show an error popup and exit."""
    mock_popup = MagicMock()

    with (
        patch("genau_vr.app._parse_args"),
        patch("genau_vr.app._load_config", return_value={}),
        patch("genau_vr.app._configure_logging", return_value=(MagicMock(), MagicMock())),
        patch("genau_vr.app.vr_runtime.ensure_ready", return_value=_ready()),
        patch("genau_vr.app._resolve_clip_list", return_value=["fake.mp4"]),
        patch("genau_vr.app.load_clip", return_value=[MagicMock(shape=(100, 200, 3))]),
        patch("genau_vr.vr_renderer.VRRenderer"),
        patch("genau_vr.vr_session.VRSession.__init__", side_effect=RuntimeError("No HMD found")),
        patch("genau_vr.app._show_error_popup", mock_popup),
        patch("genau.win32.set_app_user_model_id"),
        patch("genau.win32.stamp_pinned_shortcuts"),
    ):
        from genau_vr.app import main
        main([])

    mock_popup.assert_called_once()
    msg = mock_popup.call_args[0][0]
    assert "No HMD found" in msg


def test_main_explains_an_absent_headset_without_decoding_a_clip():
    """Nothing is worth decoding until VR answers — and the reason must be on screen."""
    mock_popup = MagicMock()
    not_ready = Probe(Readiness.NO_HEADSET, detail="powered off")

    with (
        patch("genau_vr.app._parse_args"),
        patch("genau_vr.app._load_config", return_value={}),
        patch("genau_vr.app._configure_logging", return_value=(MagicMock(), MagicMock())),
        patch("genau_vr.app.vr_runtime.ensure_ready", return_value=not_ready),
        patch("genau_vr.app.load_clip") as load_clip,
        patch("genau_vr.app._show_error_popup", mock_popup),
        patch("genau.win32.set_app_user_model_id"),
        patch("genau.win32.stamp_pinned_shortcuts"),
    ):
        from genau_vr.app import main
        main([])

    load_clip.assert_not_called()
    mock_popup.assert_called_once()
    assert "powered off" in mock_popup.call_args[0][0]


def test_main_puts_a_failure_that_is_not_about_vr_on_screen_too():
    """A missing clips folder used to print to a stderr that pythonw throws away."""
    mock_popup = MagicMock()

    with (
        patch("genau_vr.app._parse_args"),
        patch("genau_vr.app._load_config", return_value={}),
        patch("genau_vr.app._configure_logging", return_value=(MagicMock(), MagicMock())),
        patch("genau_vr.app.vr_runtime.ensure_ready", return_value=_ready()),
        patch("genau_vr.app._resolve_clip_list", side_effect=RuntimeError("no clips_dir")),
        patch("genau_vr.app._show_error_popup", mock_popup),
        patch("genau.win32.set_app_user_model_id"),
        patch("genau.win32.stamp_pinned_shortcuts"),
    ):
        from genau_vr.app import main
        main([])

    mock_popup.assert_called_once()
    assert "no clips_dir" in mock_popup.call_args[0][0]


def test_error_popup_is_topmost_so_a_hidden_launch_cannot_bury_it():
    """Launched from a shortcut, GenauVR has no foreground rights to claim."""
    user32 = MagicMock()
    with patch("genau_vr.app.ctypes.windll") as windll:
        windll.user32 = user32
        from genau_vr.app import _show_error_popup
        _show_error_popup("something went wrong")

    flags = user32.MessageBoxW.call_args[0][3]
    MB_SETFOREGROUND, MB_TOPMOST = 0x00010000, 0x00040000
    assert flags & MB_SETFOREGROUND
    assert flags & MB_TOPMOST


def test_resolve_clip_list_raises_instead_of_exiting_on_a_missing_clip(tmp_path):
    """sys.exit under pythonw is indistinguishable from a crash; an exception reaches the popup."""
    from genau_vr.app import _resolve_clip_list

    args = MagicMock(clip=str(tmp_path / "nope.mp4"))
    with pytest.raises(FileNotFoundError):
        _resolve_clip_list(args, {})


def test_resolve_clip_list_raises_when_the_config_names_no_clips():
    from genau_vr.app import _resolve_clip_list

    with pytest.raises(RuntimeError):
        _resolve_clip_list(MagicMock(clip=None), {})


def test_main_keeps_the_crash_log_open_for_the_whole_run_then_closes_it():
    """faulthandler writes to the file's fd — drop the object and a native crash goes unrecorded."""
    log, fault_fp = MagicMock(), MagicMock()

    with (
        patch("genau_vr.app._configure_logging", return_value=(log, fault_fp)),
        patch("genau_vr.app._start") as start,
        patch("genau_vr.app._show_error_popup"),
    ):
        start.side_effect = lambda *a: fault_fp.close.assert_not_called()
        from genau_vr.app import main
        main([])

    fault_fp.close.assert_called_once()


class TestWhichFolderTheClipsComeFrom:
    """GenauVR has a config key of its own for a reason: the flat clips a
    classic Genau session shows are not the 180-degree ones a headset wants."""

    @staticmethod
    def _clip_in(folder: Path, name: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        clip = folder / name
        clip.write_bytes(b"x")
        return clip

    def test_a_named_clip_is_the_whole_list(self, tmp_path):
        from genau_vr.app import _resolve_clip_list

        clip = self._clip_in(tmp_path, "scene one.mp4")

        assert _resolve_clip_list(MagicMock(clip=str(clip)), {}) == [clip]

    def test_the_vr_folder_wins_over_the_shared_one(self, tmp_path):
        from genau_vr.app import _resolve_clip_list

        vr = self._clip_in(tmp_path / "vr", "vr scene.mp4")
        self._clip_in(tmp_path / "flat", "flat scene.mp4")

        found = _resolve_clip_list(MagicMock(clip=None), {
            "vr_clips_dir": str(tmp_path / "vr"),
            "clips_dir": str(tmp_path / "flat"),
        })

        assert found == [vr]

    def test_a_vr_folder_that_is_not_there_falls_back_to_the_shared_one(self, tmp_path):
        """The key can be configured ahead of the folder existing, and a headset
        showing nothing is worse than one showing flat clips."""
        from genau_vr.app import _resolve_clip_list

        flat = self._clip_in(tmp_path / "flat", "flat scene.mp4")

        found = _resolve_clip_list(MagicMock(clip=None), {
            "vr_clips_dir": str(tmp_path / "not-here"),
            "clips_dir": str(tmp_path / "flat"),
        })

        assert found == [flat]


class TestFindingAClipsAudio:
    """The sound sits in an audio/ folder beside the clips folder, under the
    clip's own name."""

    def test_it_is_the_mp3_named_after_the_clip(self, tmp_path):
        from genau_vr.app import AudioPlayer

        (tmp_path / "clips").mkdir()
        (tmp_path / "audio").mkdir()
        clip = tmp_path / "clips" / "scene one.mp4"
        mp3 = tmp_path / "audio" / "scene one.mp3"
        mp3.write_bytes(b"x")

        assert AudioPlayer._find_audio(clip) == mp3

    def test_a_clip_with_no_sound_beside_it_finds_none(self, tmp_path):
        from genau_vr.app import AudioPlayer

        (tmp_path / "clips").mkdir()
        (tmp_path / "audio").mkdir()

        assert AudioPlayer._find_audio(tmp_path / "clips" / "silent.mp4") is None

    def test_a_clips_folder_with_no_audio_folder_beside_it_finds_none(self, tmp_path):
        from genau_vr.app import AudioPlayer

        (tmp_path / "clips").mkdir()

        assert AudioPlayer._find_audio(tmp_path / "clips" / "scene one.mp4") is None


class TestTiltingTheView:
    """The controller's pitch adjustment, as a rotation about the X axis."""

    def test_a_quarter_turn_takes_up_onto_the_axis_pointing_away(self):
        """Up is +Y and away is -Z in this space, so a positive quarter turn
        tips the view down toward the floor.  Flip the sign and the controller
        pitches the other way."""
        from genau_vr.app import _pitch_rotation_matrix

        turned = _pitch_rotation_matrix(math.pi / 2) @ np.array(
            [0.0, 1.0, 0.0, 1.0], dtype=np.float32)

        assert turned[:3] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)

    def test_no_turn_leaves_every_axis_where_it_was(self):
        from genau_vr.app import _pitch_rotation_matrix

        assert _pitch_rotation_matrix(0.0) == pytest.approx(np.eye(4))

    def test_it_only_touches_the_two_axes_it_turns_between(self):
        """X is the axis being turned about and W carries the translation, so a
        rotation that moved either would drag the whole scene with it."""
        from genau_vr.app import _pitch_rotation_matrix

        turned = _pitch_rotation_matrix(math.pi / 3)

        assert turned[0] == pytest.approx([1.0, 0.0, 0.0, 0.0])
        assert turned[3] == pytest.approx([0.0, 0.0, 0.0, 1.0])
