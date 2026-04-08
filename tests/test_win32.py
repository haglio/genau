"""Tests for genau.win32 taskbar identity helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from genau.win32 import stamp_pinned_shortcuts


@pytest.fixture
def _fake_pin_dir(tmp_path):
    """Set APPDATA so stamp_pinned_shortcuts finds a fake taskbar pin dir."""
    pin_dir = (
        tmp_path
        / "Microsoft"
        / "Internet Explorer"
        / "Quick Launch"
        / "User Pinned"
        / "TaskBar"
    )
    pin_dir.mkdir(parents=True)
    return pin_dir


class TestStampPinnedShortcuts:
    def test_stamps_matching_shortcut(self, _fake_pin_dir):
        lnk = _fake_pin_dir / "Genau.lnk"
        lnk.write_bytes(b"")

        with (
            patch("os.environ", {"APPDATA": str(_fake_pin_dir.parent.parent.parent.parent.parent)}),
            patch("genau.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("Genau.App", include="genau", exclude="genauvr")

        mock_set.assert_called_once_with(str(lnk), "Genau.App")

    def test_exclude_prevents_match(self, _fake_pin_dir):
        lnk = _fake_pin_dir / "GenauVR.lnk"
        lnk.write_bytes(b"")

        with (
            patch("os.environ", {"APPDATA": str(_fake_pin_dir.parent.parent.parent.parent.parent)}),
            patch("genau.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("Genau.App", include="genau", exclude="genauvr")

        mock_set.assert_not_called()

    def test_vr_shortcut_stamps_only_vr(self, _fake_pin_dir):
        genau_lnk = _fake_pin_dir / "Genau.lnk"
        genau_lnk.write_bytes(b"")
        vr_lnk = _fake_pin_dir / "GenauVR.lnk"
        vr_lnk.write_bytes(b"")

        with (
            patch("os.environ", {"APPDATA": str(_fake_pin_dir.parent.parent.parent.parent.parent)}),
            patch("genau.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("GenauVR.App", include="genauvr")

        mock_set.assert_called_once_with(str(vr_lnk), "GenauVR.App")
