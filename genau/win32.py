"""Win32 for Genau's window: the color-key transparency of the HUD layer."""
from __future__ import annotations

import logging

from genau.win32_loader import load_dll

_user32 = load_dll("user32")
_kernel32 = load_dll("kernel32")

logger = logging.getLogger(__name__)

# Win32 window styles, for the transparency below.
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x80000
_LWA_COLORKEY = 0x1


def _colorref(rgb: tuple[int, int, int]) -> int:
    """A Win32 COLORREF, which is 0x00BBGGRR — the reverse of RGB.

    Written the wrong way round the key matches a color nothing paints, so
    every pixel stays opaque and the HUD hides the player underneath it.
    """
    red, green, blue = rgb
    return red | (green << 8) | (blue << 16)


class LayeredWindow:
    """Color-key transparency on one window, whose handle is taken once.

    The handle is found by the window's caption at construction, while the
    caption is still the one the window was created with.  Looking it up again
    on every toggle is what tied the transparency to the title: the title
    changes when the HUD comes up, so the lookup had to happen after the rename
    and before the toggle -- an ordering held together by a comment, in a window
    fun_time separately finds by caption substring.

    A handle that cannot be found is said once and then let be: the transparency
    is what lets Nau's video show through Genau's overlay, so losing it costs
    the video-mode look rather than the session.
    """

    def __init__(self, title: str, color_key: tuple[int, int, int], *, user32=None):
        self._user32 = user32 if user32 is not None else _user32
        self._color_key = color_key
        self.hwnd = self._user32.FindWindowW(None, title)
        if not self.hwnd:
            logger.warning("HUD: no window found with the caption %r", title)

    def set_transparent(self, transparent: bool) -> None:
        if not self.hwnd:
            return
        style = self._user32.GetWindowLongW(self.hwnd, _GWL_EXSTYLE)
        if not transparent:
            self._user32.SetWindowLongW(
                self.hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED)
            logger.info("HUD: layered window disabled")
            return
        self._user32.SetWindowLongW(
            self.hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
        key = _colorref(self._color_key)
        if self._user32.SetLayeredWindowAttributes(self.hwnd, key, 0, _LWA_COLORKEY):
            logger.info("HUD: layered window enabled (hwnd=%#x, colorkey=%#08x)",
                        self.hwnd, key)
        else:
            logger.warning("HUD: SetLayeredWindowAttributes failed (error %d)",
                           _kernel32.GetLastError())
