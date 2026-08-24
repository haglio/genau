"""Tests for genau.win32 taskbar identity helpers."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genau import win32_loader
from genau.config import DEFAULT_CONFIG_PATH
from genau.win32 import stamp_pinned_shortcuts, take_taskbar_identity

REPO_DIR = Path(__file__).resolve().parent.parent

# The names ``ctypes`` grows only on Windows, and that this module reaches for
# while it is being imported.
_WIN32_CTYPES_NAMES = ("windll", "oledll", "WinDLL", "OleDLL", "WINFUNCTYPE", "HRESULT")

_STRIP_WIN32_FROM_CTYPES = f"""
import ctypes, ctypes.wintypes
for _name in {_WIN32_CTYPES_NAMES!r}:
    if hasattr(ctypes, _name):
        delattr(ctypes, _name)
"""


def _run_without_the_win32_ctypes_surface(body):
    """Run *body* in a child whose ``ctypes`` has had its Windows half removed.

    ``PYTHONPATH`` is dropped so the child cannot pick up a shim that fakes that
    surface back in, the way a run on a developer's non-Windows machine does.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", _STRIP_WIN32_FROM_CTYPES + body],
        cwd=str(REPO_DIR), env=env, capture_output=True, text=True, timeout=180,
    )


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


class TestTakeTaskbarIdentity:
    """The process identity is ours to set; the pin is not always ours to write.

    ``set_app_user_model_id`` only labels this process — no shared state, so it
    runs for whoever started us.  Stamping writes into ``%APPDATA%``, outside
    every checkout, and the pin belongs to the app it launches: a session on an
    explicit ``--config`` (a test run's temp one, an alternate of the
    developer's) is some other instance, and reaching into the user's shell to
    relabel a shortcut that points at neither of them is not its business.

    Fun Time's integration suite launches Nau and Genau on a temp config, so
    every run was doing exactly that.
    """

    def test_a_session_on_another_config_leaves_the_pin_alone(self, tmp_path):
        with (
            patch("genau.win32.set_app_user_model_id") as mock_identity,
            patch("genau.win32.stamp_pinned_shortcuts") as mock_stamp,
        ):
            take_taskbar_identity(
                "Genau.App", include="genau", config_path=tmp_path / "temp_config.json",
            )

        mock_stamp.assert_not_called()
        # Still ours to claim: it labels this process and nothing else.
        mock_identity.assert_called_once_with("Genau.App")

    def test_the_installed_app_still_stamps_its_own_pin(self):
        with (
            patch("genau.win32.set_app_user_model_id"),
            patch("genau.win32.stamp_pinned_shortcuts") as mock_stamp,
        ):
            take_taskbar_identity(
                "Genau.App", include="genau", exclude="genauvr",
                config_path=DEFAULT_CONFIG_PATH,
            )

        mock_stamp.assert_called_once_with("Genau.App", include="genau", exclude="genauvr")

    def test_a_relative_spelling_of_the_installed_config_still_counts(self):
        """Nau and GenauVR each build their own path to the one config file, and
        an argparse default arrives unresolved.  Comparing the spellings would
        make the same file read as a different app."""
        spelled_differently = DEFAULT_CONFIG_PATH.parent / "." / DEFAULT_CONFIG_PATH.name

        with (
            patch("genau.win32.set_app_user_model_id"),
            patch("genau.win32.stamp_pinned_shortcuts") as mock_stamp,
        ):
            take_taskbar_identity("Nau.App", include="nau", config_path=spelled_differently)

        mock_stamp.assert_called_once()

    def test_a_failed_identity_call_does_not_stop_the_launch(self):
        """SetCurrentProcessExplicitAppUserModelID is cosmetic — losing it costs
        the taskbar icon, and is never worth failing to start over."""
        with (
            patch("genau.win32.set_app_user_model_id", side_effect=OSError("nope")),
            patch("genau.win32.stamp_pinned_shortcuts") as mock_stamp,
        ):
            take_taskbar_identity("Genau.App", include="genau", config_path=DEFAULT_CONFIG_PATH)

        mock_stamp.assert_called_once()


class TestWhereWin32CannotBeBound:
    """What this module does on a machine whose ctypes has no Windows half.

    It bound shell32 and ole32 while it was being imported, so off Windows the
    import raised — and ``genau_vr/app.py`` names it, so this file was not a set
    of Windows tests failing, it was a collection error that took every test in
    it out of the run.

    The child interpreters below delete that half of ``ctypes`` before importing
    anything, so these ask the same question on Windows as anywhere else.
    """

    def test_the_module_imports_where_ctypes_has_no_windll(self):
        result = _run_without_the_win32_ctypes_surface(
            "import genau.win32\n"
            "from genau.win32_loader import WIN32_AVAILABLE\n"
            "assert WIN32_AVAILABLE is False, WIN32_AVAILABLE\n"
        )

        assert result.returncode == 0, result.stderr

    def test_the_flag_says_whether_this_ctypes_can_bind_a_dll(self):
        assert win32_loader.WIN32_AVAILABLE is hasattr(ctypes, "windll")

    def test_a_call_that_reaches_an_unbound_entry_point_names_it(self):
        """The stand-in must never pass for a call that worked."""
        with patch.object(win32_loader, "WIN32_AVAILABLE", False):
            shell32 = win32_loader.load_dll("shell32")

            with pytest.raises(
                win32_loader.Win32Unavailable,
                match=r"shell32\.SetCurrentProcessExplicitAppUserModelID",
            ):
                shell32.SetCurrentProcessExplicitAppUserModelID("Genau.App")

    def test_an_unbound_entry_point_is_the_same_object_every_time(self):
        """A test that patches one has to be patching what the code will call."""
        with patch.object(win32_loader, "WIN32_AVAILABLE", False):
            ole32 = win32_loader.load_dll("ole32")

            assert ole32.CoCreateInstance is ole32.CoCreateInstance
