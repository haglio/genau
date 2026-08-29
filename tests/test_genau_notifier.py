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


def test_announce_visible_says_the_clip_first_and_then_that_the_window_is_up():
    """A reader learns what it is looking at before it learns it is there."""
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.announce_visible(Path("demo.mp4"))

    assert sock.sent == [
        (b"CLIP demo", ("127.0.0.1", 9999)),
        (b"VISIBLE 1", ("127.0.0.1", 9999)),
    ]


def test_announce_visible_says_nothing_on_every_tick_after_the_first():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.announce_visible(Path("demo.mp4"))
    notifier.announce_visible(Path("other.mp4"))
    notifier.announce_visible(Path("third.mp4"))

    assert sock.sent == [
        (b"CLIP demo", ("127.0.0.1", 9999)),
        (b"VISIBLE 1", ("127.0.0.1", 9999)),
    ]


def test_announce_visible_still_says_it_is_up_before_a_clip_has_settled():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.announce_visible(None)

    assert sock.sent == [(b"VISIBLE 1", ("127.0.0.1", 9999))]


def test_close_closes_socket():
    sock = FakeSocket()
    notifier = GenauNotifier("127.0.0.1", 9999, sock=sock)

    notifier.close()

    assert sock.closed is True
