from __future__ import annotations

from enum import Enum, auto

from .funscript import Funscript, snap_loop


class LoopState(Enum):
    NORMAL = auto()
    MARKING = auto()
    LOOPING = auto()


class LoopController:
    def __init__(self, funscript: Funscript) -> None:
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

    def on_space_down(self, position_ms: int) -> None:
        if self._state == LoopState.NORMAL:
            self._in_ms = position_ms
            self._state = LoopState.MARKING
        elif self._state == LoopState.LOOPING:
            self._in_ms = None
            self._out_ms = None
            self._state = LoopState.NORMAL

    def on_space_up(self, position_ms: int) -> None:
        if self._state != LoopState.MARKING:
            return
        self._in_ms, self._out_ms = snap_loop(
            self._funscript, self._in_ms, position_ms,
        )
        self._state = LoopState.LOOPING

    def check_loop(self, position_ms: int) -> int | None:
        if self._state != LoopState.LOOPING:
            return None
        if position_ms >= self._out_ms:
            return self._in_ms
        return None
