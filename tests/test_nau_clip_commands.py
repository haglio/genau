from __future__ import annotations

from nau.runtime import apply_command


class _Spy:
    loop_state = "normal"


def test_play_compilation_invokes_callback():
    calls: list[str] = []
    assert apply_command("PLAY_COMPILATION", _Spy(), play_compilation=lambda: calls.append("c"))
    assert calls == ["c"]


def test_play_full_vid_invokes_callback():
    calls: list[str] = []
    assert apply_command("PLAY_FULL_VID", _Spy(), play_full_vid=lambda: calls.append("f"))
    assert calls == ["f"]


def test_play_money_shot_invokes_callback():
    calls: list[str] = []
    assert apply_command("PLAY_MONEY_SHOT", _Spy(), play_money_shot=lambda: calls.append("m"))
    assert calls == ["m"]


def test_clip_commands_without_callbacks_return_false():
    assert apply_command("PLAY_COMPILATION", _Spy()) is False
    assert apply_command("PLAY_FULL_VID", _Spy()) is False
    assert apply_command("PLAY_MONEY_SHOT", _Spy()) is False
