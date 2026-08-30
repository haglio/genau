"""Runtime command dispatch — one line in, one control moved."""
from __future__ import annotations

import logging

from genau.control_registry import look_up

from .controls import VERBS, GenauVrControls


logger = logging.getLogger(__name__)


def apply_runtime_command(command, controls: GenauVrControls) -> None:
    """Act on one command, or say on the log that we cannot.

    The dispatcher reports an unanswered verb itself rather than returning a
    flag for a caller to check: it is the only thing that knows, and there is
    one of it rather than one per call site. Two kinds land here — a verb no
    branch matches, and a verb whose collaborator this build did not wire —
    and both mean the same thing to whoever sent it, which is that nothing
    happened.
    """
    if not look_up(command, VERBS, controls):
        logger.warning("Unhandled command: %s", str(command).strip())
