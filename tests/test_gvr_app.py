"""Tests for genau_vr.app startup error handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from genau_vr.vr_runtime import Probe, Readiness


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
