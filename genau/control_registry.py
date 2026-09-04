"""How a control is declared, for any of the players in this repo.

A control is one thing a person can move.  This module says what that record
looks like and nothing about what Genau's controls are: what they are lives in
:mod:`genau.controls`, and GenauVR's in :mod:`genau_vr.controls`, each against
its own set of collaborators.

Its real home is ``player_core``, beside the file channel the verbs arrive on --
this is the family's shape, not Genau's -- and it sits here until a change to
that sibling repo can land alongside.

The point of the record is that a control is declared once.  Before it, adding
one meant a keyword parameter and a branch in the dispatcher, a parameter and an
attribute and a hand-off line on the tick, and a branch in the key handler --
four to six files for one control, and no way to see from any of them what the
whole control was.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# What a verb does when it lands: move something on the controls, and say
# whether it could.  The value is the rest of the line after the verb, empty
# when there was none.
Act = Callable[[Any, str], bool]


@dataclass(frozen=True)
class Verb:
    """One spelling an orchestrator may send, and the key that means the same.

    ``takes_a_value`` is part of the spelling, not a convenience: ``AMP`` alone
    and ``SPEED_UP 5`` are both refused, because half a command is not a command.

    ``key`` is the name of the pygame constant a press on the player's own
    window arrives as -- the name rather than the constant, so a registry stays
    free of the window library.  Declaring it beside the verb is the point: a
    key and a verb that mean the same thing are one line, so they cannot drift
    into meaning two things, which they had (see the `/` key in CHANGELOG.md).
    """

    spelling: str
    act: Act
    takes_a_value: bool = False
    key: str | None = None


@dataclass(frozen=True)
class Control:
    """One thing a person can move: what it is called, what it cannot act
    without, and the verbs that move it.

    ``needs`` names fields of whatever controls object the player passes to
    :func:`act`.  A build that did not wire one of them refuses this control's
    verbs and logs them, rather than acting on half of what was asked -- the
    same rule an ``and X is not None`` guard on every branch used to spell out
    one verb at a time.
    """

    name: str
    verbs: tuple[Verb, ...]
    needs: tuple[str, ...] = ()

    def can_act(self, controls: Any) -> bool:
        return all(getattr(controls, name) is not None for name in self.needs)


def bind(controls: tuple[Control, ...]) -> Mapping[str, tuple[Control, Verb]]:
    """Flatten a registry to the map a dispatcher looks a verb up in.

    Two controls claiming one spelling is refused here rather than resolved: the
    loser would go silently unreachable, which is precisely the drift the
    registry exists to stop.  It is an import-time answer, so a malformed
    registry cannot get as far as a running app.
    """
    bound: dict[str, tuple[Control, Verb]] = {}
    for control in controls:
        for verb in control.verbs:
            if verb.spelling in bound:
                other, _ = bound[verb.spelling]
                raise ValueError(
                    f"{verb.spelling} is claimed by both "
                    f"{other.name} and {control.name}"
                )
            bound[verb.spelling] = (control, verb)
    return bound


def bind_keys(controls: tuple[Control, ...]) -> Mapping[str, tuple[Control, Verb]]:
    """The keys a registry declares, by the name of the pygame constant.

    Two verbs on one key is refused the same way and for the same reason as two
    controls on one verb: whichever the window looked up second would never
    fire, and nothing would say so.
    """
    bound: dict[str, tuple[Control, Verb]] = {}
    for control in controls:
        for verb in control.verbs:
            if verb.key is None:
                continue
            if verb.key in bound:
                _, other = bound[verb.key]
                raise ValueError(
                    f"{verb.key} is claimed by both "
                    f"{other.spelling} and {verb.spelling}"
                )
            bound[verb.key] = (control, verb)
    return bound


def act(control: Control, verb: Verb, controls: Any, value: str) -> bool:
    """Run a declared verb, or say why it cannot run.

    Three ways it does not: a control this build did not wire, a value on a verb
    that takes none, and none on a verb that wants one.  All three read the same
    to whoever sent it -- nothing happened.
    """
    if not control.can_act(controls):
        return False
    if verb.takes_a_value != bool(value):
        return False
    return verb.act(controls, value)


def look_up(
    command, verbs: Mapping[str, tuple[Control, Verb]], controls: Any,
) -> bool:
    """Look one line up in *verbs* and run what it names.

    Case and surrounding space do not matter: the file channel carries what a
    voice listener heard and what a dashboard button posted, and neither is
    typed carefully.  Whatever follows the verb is its value, unread by a verb
    that takes none.
    """
    if not command:
        return False
    said = command.strip().upper().split(None, 1)
    if not said:
        return False
    declared = verbs.get(said[0])
    if declared is None:
        return False
    return act(*declared, controls, said[1] if len(said) > 1 else "")
