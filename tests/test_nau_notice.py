from __future__ import annotations

from nau.notice import NoticeWriter


def _read(path):
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_say_publishes_the_message_and_level(tmp_path):
    path = tmp_path / "state" / "nau_notice.txt"

    assert NoticeWriter(path, clock=lambda: 10.0).say("full video not available") is True

    assert _read(path) == {"seq": "10.000", "level": "error",
                           "message": "full video not available"}


def test_each_say_advances_the_sequence(tmp_path):
    path = tmp_path / "nau_notice.txt"
    ticks = iter([10.0, 20.0])
    writer = NoticeWriter(path, clock=lambda: next(ticks))
    writer.say("first")
    writer.say("second", level="notice")

    assert _read(path) == {"seq": "20.000", "level": "notice", "message": "second"}


def test_a_restarted_writer_still_reads_as_newer(tmp_path):
    """A counter restarts at 1 whenever Nau does, so its notices read as older
    than the previous session's and never flashed. A clock stamp cannot."""
    path = tmp_path / "nau_notice.txt"
    NoticeWriter(path, clock=lambda: 100.0).say("before the restart")
    NoticeWriter(path, clock=lambda: 101.0).say("after the restart")

    assert float(_read(path)["seq"]) > 100.0


def test_without_a_path_it_is_inert():
    assert NoticeWriter(None).say("nothing doing") is False
