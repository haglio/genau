"""The main console Genau draws over its clip, and the presses that land on it.

In genau mode Genau owns the main slot, so it draws the panel Nau draws in the
other modes — the same painter, so it reads the same whichever player is showing
it — and takes its clicks.  Drawing it and hitting it are one object because
they are one surface: what is clickable is exactly the rects the last painting
laid down, and the hover the pointer leaves is read back at the next painting.

The window it is blitted into knows none of this, which is why it is not there.
"""
from __future__ import annotations

from player_core.console_hud import ConsoleHud, ConsolePainter


class ConsolePanel:
    def __init__(self) -> None:
        self._painter = ConsolePainter()
        # None until the refresh loop has a panel to show: it arrives published
        # by Fun Time rather than being built here.
        self._panel: ConsoleHud | None = None
        self._hover: tuple[int, int] | None = None

    def show(self, console: ConsoleHud | None) -> None:
        self._panel = console

    @property
    def showing(self) -> bool:
        return self._panel is not None

    def press_at(self, mx: int, my: int) -> str:
        """The command a press at ``(mx, my)`` posts, "" over no control.

        A press on one of the drive readout's bars takes hold of it, so the
        pointer goes on setting that level until :meth:`release`.
        """
        return self._painter.press_at(mx, my)

    def drag_to(self, mx: int, my: int) -> str:
        """The command the pointer posts while a bar is held, "" while none is."""
        return self._painter.drag_to(mx, my)

    def release(self) -> None:
        """Let go of whichever bar a press took hold of."""
        self._painter.release()

    def hover_at(self, mx: int, my: int) -> None:
        """Remember where the cursor is, so a button under it names itself;
        forgotten when it is over nothing."""
        self._hover = self._painter.hover_at(mx, my)

    def rgba(self) -> tuple[bytes, tuple[int, int]] | None:
        """This frame's panel as ``(rgba_bytes, size)``, or None with none to
        show.  The size varies with the contents, so the caller sizes its blit
        from what comes back."""
        if self._panel is None:
            return None
        return self._painter.rgba(self._panel, hover=self._hover)
