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

    def close(self) -> None:
        self.sock.close()
