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
from genau.win32 import (
    set_shortcut_app_user_model_id,
    stamp_pinned_shortcuts,
    take_taskbar_identity,
)

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


class TestTheApartmentStampingRunsIn:
    """Only an initialisation that succeeded may be undone.

    ``CoInitializeEx`` answers ``S_OK`` when it opened the apartment, ``S_FALSE``
    when the thread already had one -- both took a reference this thread owes a
    ``CoUninitialize`` back -- and a failure HRESULT when it took none, which on
    this path means ``RPC_E_CHANGED_MODE``: something else put the thread in the
    other concurrency model first.  Uninitialising then decrements *that*
    initialisation's count, and the apartment its owner is holding objects in
    can go out from under them.
    """

    RPC_E_CHANGED_MODE = -2147417850  # 0x80010106, as a ctypes HRESULT comes back
    S_FALSE = 1
    LNK = r"C:\Users\Example\AppData\Roaming\Genau.lnk"

    def test_an_apartment_this_call_did_not_open_is_not_closed(self):
        ole32 = MagicMock()
        ole32.CoInitializeEx.return_value = self.RPC_E_CHANGED_MODE

        with (
            patch("genau.win32._ole32", ole32),
            patch("genau.win32._set_lnk_aumid") as stamp,
            pytest.raises(OSError, match="CoInitializeEx failed"),
        ):
            set_shortcut_app_user_model_id(self.LNK, "Genau.App")

        stamp.assert_not_called()
        ole32.CoUninitialize.assert_not_called()

    def test_an_apartment_that_was_already_open_is_still_closed(self):
        """S_FALSE is a successful init, so this thread owes the balancing call."""
        ole32 = MagicMock()
        ole32.CoInitializeEx.return_value = self.S_FALSE

        with patch("genau.win32._ole32", ole32), patch("genau.win32._set_lnk_aumid") as stamp:
            set_shortcut_app_user_model_id(self.LNK, "Genau.App")

        stamp.assert_called_once_with(self.LNK, "Genau.App")
        ole32.CoUninitialize.assert_called_once()


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


class TestTheHudTransparency:
    """Color-key transparency is what lets Nau's video show through Genau's
    overlay in video mode.  It was thirty lines of inline ctypes inside the view,
    reached only through a method every test replaced with a mock -- so the
    COLORREF conversion, the two style edits and the failure report had never
    been run by anything.
    """

    KEY = (1, 0, 1)

    @staticmethod
    def _user32(hwnd=0x2A, style=0x0, set_layered=1):
        stand_in = MagicMock()
        stand_in.FindWindowW.return_value = hwnd
        stand_in.GetWindowLongW.return_value = style
        stand_in.SetLayeredWindowAttributes.return_value = set_layered
        return stand_in

    def _layered(self, **over):
        from genau.win32 import LayeredWindow

        return LayeredWindow("Genau", self.KEY, user32=self._user32(**over))

    def test_it_finds_the_window_by_the_caption_it_was_given(self):
        user32 = self._user32()
        from genau.win32 import LayeredWindow

        LayeredWindow("Genau", self.KEY, user32=user32)

        user32.FindWindowW.assert_called_once_with(None, "Genau")

    def test_it_looks_the_handle_up_once_and_holds_it(self):
        """Looked up per toggle, it would be found by whatever the caption had
        become -- which the HUD changes on the very line before."""
        layered = self._layered()

        layered.set_transparent(True)
        layered.set_transparent(False)

        assert layered._user32.FindWindowW.call_count == 1

    def test_turning_it_on_adds_the_layered_style_to_the_ones_already_there(self):
        """Assigned rather than or-ed, every other style on the window is lost
        — including the borderless one Fun Time's slot depends on."""
        WS_EX_LAYERED, existing = 0x80000, 0x00040000
        layered = self._layered(style=existing)

        layered.set_transparent(True)

        _hwnd, _index, style = layered._user32.SetWindowLongW.call_args[0]
        assert style == existing | WS_EX_LAYERED

    def test_turning_it_off_takes_only_that_style_away(self):
        WS_EX_LAYERED, existing = 0x80000, 0x00040000
        layered = self._layered(style=existing | WS_EX_LAYERED)

        layered.set_transparent(False)

        _hwnd, _index, style = layered._user32.SetWindowLongW.call_args[0]
        assert style == existing

    def test_the_color_key_goes_out_the_way_win32_reads_it(self):
        """COLORREF is 0x00BBGGRR — the reverse of RGB.  Written the wrong way
        round the key matches a color nothing paints, so every pixel stays
        opaque and the HUD hides the player underneath it."""
        layered = self._layered()

        layered.set_transparent(True)

        _hwnd, key, _alpha, _flags = layered._user32.SetLayeredWindowAttributes.call_args[0]
        assert key == 0x00010001            # (1, 0, 1) as BBGGRR

    def test_it_asks_for_the_color_key_and_not_for_whole_window_alpha(self):
        LWA_COLORKEY = 0x1
        layered = self._layered()

        layered.set_transparent(True)

        _hwnd, _key, _alpha, flags = layered._user32.SetLayeredWindowAttributes.call_args[0]
        assert flags == LWA_COLORKEY

    def test_turning_it_off_does_not_set_a_color_key(self):
        layered = self._layered()

        layered.set_transparent(False)

        assert layered._user32.SetLayeredWindowAttributes.call_count == 0

    def test_a_window_it_could_not_find_is_said_once_and_then_let_be(self, caplog):
        """Losing the transparency costs the video-mode look, not the session."""
        with caplog.at_level("WARNING", logger="genau.win32"):
            layered = self._layered(hwnd=0)
            layered.set_transparent(True)

        assert layered.hwnd == 0
        assert layered._user32.SetWindowLongW.call_count == 0
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1

    def test_a_refused_color_key_is_reported_rather_than_assumed(self, caplog):
        layered = self._layered(set_layered=0)

        with caplog.at_level("WARNING", logger="genau.win32"):
            layered.set_transparent(True)

        assert "SetLayeredWindowAttributes" in caplog.text
