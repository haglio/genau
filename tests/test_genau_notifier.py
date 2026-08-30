from __future__ import annotations

from pathlib import Path
from genau.notifier import GenauNotifier


class FakeSocket:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        self.closed = True


def test_notify_clip_sends_clip_stem():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.notify_clip(Path("demo.mp4"))

    assert sock.sent == [(b"CLIP demo", ("127.0.0.1", 9999))]


def test_notify_visible_deduplicates_repeated_state():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.notify_visible(True)
    notifier.notify_visible(True)
    notifier.notify_visible(False)

    assert sock.sent == [
        (b"VISIBLE 1", ("127.0.0.1", 9999)),
        (b"VISIBLE 0", ("127.0.0.1", 9999)),
    ]


def test_the_notifier_has_only_the_two_things_it_says():
    """CLIP and VISIBLE, each with one caller.

    A third method wrapped them to send both at once, for a first tick that
    had already had its CLIP sent by the clip selection a moment earlier --
    so it put the same datagram on the wire twice at every launch.
    """
    assert not hasattr(GenauNotifier, "announce_visible")


def test_close_closes_socket():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.close()

    assert sock.closed is True
