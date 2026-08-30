from __future__ import annotations

import logging

from .controls import VERBS, Control, GenauControls, Verb


logger = logging.getLogger(__name__)


def apply_runtime_command(command, controls: GenauControls) -> None:
    """Act on one command, or say on the log that we cannot.

    The dispatcher reports an unanswered verb itself rather than returning a
    flag for a caller to check: it is the only thing that knows, and there is
    one of it rather than one per call site. Two kinds land here — a verb no
    branch matches, and a verb whose collaborator this build did not wire —
    and both mean the same thing to whoever sent it, which is that nothing
    happened.
    """
    if not _dispatch(command, controls):
        logger.warning("Unhandled command: %s", str(command).strip())


def _dispatch(command, controls: GenauControls) -> bool:
    """Look one line up in the registry and run what it names.

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
    declared = VERBS.get(said[0])
    if declared is None:
        return False
    return _act(*declared, controls, said[1] if len(said) > 1 else "")


def _act(control: Control, verb: Verb, controls: GenauControls, value: str) -> bool:
    """Run a declared verb, or say why it cannot run.

    Three ways it does not: a control this build did not wire, a value on a verb
    that takes none, and none on a verb that wants one.  All three read the same
    to whoever sent it — nothing happened — and all three are logged.
    """
    if not control.can_act(controls):
        return False
    if verb.takes_a_value != bool(value):
        return False
    return verb.act(controls, value)
