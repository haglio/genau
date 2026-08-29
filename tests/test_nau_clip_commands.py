from __future__ import annotations

import pytest

from nau.runtime import apply_command


class _Spy:
    loop_state = "normal"


def test_play_compilation_invokes_callback():
    calls: list[str] = []
    apply_command("PLAY_COMPILATION", _Spy(), play_compilation=lambda: calls.append("c"))
    assert calls == ["c"]


def test_play_full_vid_invokes_callback():
    calls: list[str] = []
    apply_command("PLAY_FULL_VID", _Spy(), play_full_vid=lambda: calls.append("f"))
    assert calls == ["f"]


def test_play_clip_jump_invokes_callback():
    calls: list[str] = []
    apply_command("PLAY_CLIP_JUMP", _Spy(), play_clip_jump=lambda: calls.append("m"))
    assert calls == ["m"]


def test_jump_to_funscript_invokes_callback():
    calls: list[str] = []
    apply_command("JUMP_TO_FUNSCRIPT", _Spy(), jump_to_funscript=lambda: calls.append("j"))
    assert calls == ["j"]


def test_next_funscripted_invokes_callback():
    calls: list[str] = []
    apply_command("NEXT_FUNSCRIPTED", _Spy(), next_funscripted=lambda: calls.append("n"))
    assert calls == ["n"]


_CALLBACK_VERBS = [
    ("PLAY_COMPILATION", "play_compilation"),
    ("PLAY_FULL_VID", "play_full_vid"),
    ("PLAY_CLIP_JUMP", "play_clip_jump"),
    ("JUMP_TO_FUNSCRIPT", "jump_to_funscript"),
    ("NEXT_FUNSCRIPTED", "next_funscripted"),
]


@pytest.mark.parametrize("verb, kwarg", _CALLBACK_VERBS)
def test_a_clip_command_without_its_own_callback_reaches_no_other(verb, kwarg):
    """Fun Time sends these whether or not this build wired the callback.

    Every other callback is wired here, so a verb that fell through to a
    neighbour would show up rather than reading as a quiet no-op.
    """
    calls: list[str] = []
    wired = {
        other: (lambda name=other: calls.append(name))
        for _v, other in _CALLBACK_VERBS if other != kwarg
    }

    apply_command(verb, _Spy(), **wired)

    assert calls == []
