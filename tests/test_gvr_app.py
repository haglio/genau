"""Tests for genau_vr.app startup error handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_main_shows_error_popup_on_vr_init_failure():
    """When VRSession() raises, main should show an error popup and exit."""
    mock_popup = MagicMock()

    with (
        patch("genau_vr.app._parse_args"),
        patch("genau_vr.app._load_config", return_value={}),
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
