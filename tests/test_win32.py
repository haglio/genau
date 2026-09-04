"""Tests for genau.win32: the HUD transparency, and what binds off Windows."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genau import win32_loader

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


class TestWhereWin32CannotBeBound:
    """What this module does on a machine whose ctypes has no Windows half.

    It bound user32 while it was being imported, so off Windows the import
    raised -- and a test file that names it was then not a set of Windows
    tests failing, it was a collection error that took every test in it out of
    the run.

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
            user32 = win32_loader.load_dll("user32")

            with pytest.raises(
                win32_loader.Win32Unavailable,
                match=r"user32\.FindWindowW",
            ):
                user32.FindWindowW(None, "Genau")

    def test_an_unbound_entry_point_is_the_same_object_every_time(self):
        """A test that patches one has to be patching what the code will call."""
        with patch.object(win32_loader, "WIN32_AVAILABLE", False):
            user32 = win32_loader.load_dll("user32")

            assert user32.FindWindowW is user32.FindWindowW


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
