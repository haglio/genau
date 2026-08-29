from __future__ import annotations

import socket
from pathlib import Path


class GenauNotifier:
    def __init__(self, host: str, port: int, *, sock=None):
        self.host = host
        self.port = port
        self.sock = sock if sock is not None else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_visible_sent: int | None = None

    def _send(self, message: str) -> None:
        self.sock.sendto(message.encode("utf-8"), (self.host, self.port))

    def notify_clip(self, path: Path) -> None:
        self._send(f"CLIP {path.stem}")

    def notify_visible(self, is_visible: bool) -> None:
        value = 1 if is_visible else 0
        if self.last_visible_sent == value:
            return
        self._send(f"VISIBLE {value}")
        self.last_visible_sent = value

    def announce_visible(self, current_clip_path: Path | None) -> None:
        """Say the window is up, and which clip is on it.

        Called every tick and speaks once: :meth:`notify_visible` drops a
        repeat, and the clip only goes out ahead of a `VISIBLE 1` that has
        not been said yet.  Turning it off is
        :meth:`notify_visible`\\ ``(False)``, which the lifecycle sends on the
        way out.
        """
        if self.last_visible_sent != 1 and current_clip_path is not None:
            self.notify_clip(current_clip_path)
        self.notify_visible(True)

    def close(self) -> None:
        self.sock.close()
