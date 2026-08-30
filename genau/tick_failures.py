"""A failing tick, said once rather than a hundred times a second.

The refresh wraps the whole tick and the main loop calls it again immediately at
up to 120fps, so a persistent fault used to write thousands of identical
tracebacks a second into genau_listener.log -- which both buries the first
occurrence and can fill the state directory the other three IPC files live in.

The first of each kind is a full traceback, because that is what a reader needs.
Every repeat after it is one debug line with no traceback, and the run of them
is counted; the count goes out when the fault gives way to another or when a
tick works again, which are the two moments it means something.
"""
from __future__ import annotations

import logging


class TickFailures:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._kind: tuple[str, str] | None = None
        self._repeats = 0

    def failed(self, exc: BaseException) -> None:
        kind = (type(exc).__name__, str(exc))
        if kind == self._kind:
            self._repeats += 1
            self.logger.debug("refresh failed again: %s", exc)
            return
        self._report_the_run()
        self._kind = kind
        self._repeats = 0
        self.logger.error("refresh failed", exc_info=exc)

    def worked(self) -> None:
        """A tick that got through, which is when a run of failures is over."""
        self._report_the_run()
        self._kind = None
        self._repeats = 0

    def _report_the_run(self) -> None:
        if self._repeats:
            self.logger.error(
                "...and %d more like it: %s", self._repeats, self._kind[1],
            )
