from __future__ import annotations

from nau.notice import NoticeWriter


def _read(path):
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_say_publishes_a_sequenced_message(tmp_path):
    path = tmp_path / "state" / "nau_notice.txt"

    assert NoticeWriter(path).say("full video not available") is True

    assert _read(path) == {"seq": "1", "level": "error",
                           "message": "full video not available"}


def test_each_say_advances_the_sequence(tmp_path):
    path = tmp_path / "nau_notice.txt"
    writer = NoticeWriter(path)
    writer.say("first")
    writer.say("second", level="notice")

    assert _read(path) == {"seq": "2", "level": "notice", "message": "second"}


def test_without_a_path_it_is_inert():
    assert NoticeWriter(None).say("nothing doing") is False
