from __future__ import annotations

import logging

from .control_registry import look_up
from .controls import VERBS, GenauControls

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
    return look_up(command, VERBS, controls)
