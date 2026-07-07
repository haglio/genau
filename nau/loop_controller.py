from __future__ import annotations

from enum import Enum, auto

from .funscript import Funscript, snap_loop


class LoopState(Enum):
    NORMAL = auto()
    MARKING = auto()
    LOOPING = auto()


class LoopController:
    def __init__(self, funscript: Funscript | None) -> None:
        self._funscript = funscript
        self._state = LoopState.NORMAL
        self._in_ms: int | None = None
        self._out_ms: int | None = None

    @property
    def state(self) -> LoopState:
        return self._state

    @property
    def in_ms(self) -> int | None:
        return self._in_ms

    @property
    def out_ms(self) -> int | None:
        return self._out_ms

    def on_record_down(self, position_ms: int) -> None:
        if self._state == LoopState.NORMAL:
            self._in_ms = position_ms
            self._state = LoopState.MARKING
        elif self._state == LoopState.LOOPING:
            self.cancel()

    def on_record_up(self, position_ms: int) -> None:
        if self._state != LoopState.MARKING:
            return
        # The record-down point is a hard floor: the loop only extends forward
        # from it. Seeks are clamped to it while marking, so an out point behind
        # the start only arises from the EOF-wrap race — floor it to the start
        # rather than let snap_loop flip the loop backwards.
        out_ms = max(position_ms, self._in_ms)
        self._in_ms, self._out_ms = snap_loop(
            self._funscript, self._in_ms, out_ms,
        )
        self._state = LoopState.LOOPING

    def cancel(self) -> None:
        self._in_ms = None
        self._out_ms = None
        self._state = LoopState.NORMAL
