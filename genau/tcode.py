"""Genau's phase-driven T-Code sender.

The wire format and the UDP sink live in ``player_core.tcode``, beneath every
OSR2 driver in the family; what stays here is the one driver that is Genau's
own — turning the stroke engine's continuous phase into rate-limited position
commands, shaped by the direct-control state.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from player_core.tcode import HandoffGlide, TCodeSink, format_tcode_command

from player_core.direct_control import phase_to_position

if TYPE_CHECKING:
    from player_core.direct_control import DirectControlState


class RateLimitedTCodeSender:
    def __init__(
        self,
        sink: TCodeSink,
        *,
        direct_state: DirectControlState | None = None,
        min_interval: float = 1.0 / 30.0,
        now_source=time.monotonic,
    ) -> None:
        self._sink = sink
        self._direct_state = direct_state
        self._min_interval = min_interval
        self._last_send_time: float = 0.0
        self._last_phase: float = 0.0
        self._stroke_phase: float = 0.0
        # Genau does not drive the device the whole time — in Hybrid a funscript
        # takes it for every scripted stretch — so it comes back to a device
        # parked wherever the script left it.  Armed here and on every takeover.
        self._glide = HandoffGlide()
        self._glide.begin()

    def take_over(self) -> None:
        """Genau has the device again: resume the stroke from the foot of its
        swing, and ease onto it.

        The funscript's turn leaves the device at its park, and the frozen
        phase could be anywhere in the cycle — resuming there aimed the first
        commands at whatever height the swing happened to freeze at, a lunge
        across most of the range.  From the bottom, the stroke rises out of
        the rest it finds the device in.
        """
        self.rest_at_bottom()
        self._glide.begin()

    def rest_at_bottom(self) -> None:
        """Put the stroke at the foot of its swing — phase 0, where every
        waveform shape's raw value is 0: the lowest point the current center
        and amplitude reach, and the nearest the stroke comes to the park.

        Called when Genau loses the device as well as when it takes it back
        (:meth:`take_over`), so the readout published through a funscript's
        turn shows the stroke that will actually resume, not wherever the
        swing froze.
        """
        self._stroke_phase = 0.0

    def _compute_position(self) -> int:
        if self._direct_state is not None:
            return phase_to_position(
                self._stroke_phase,
                shape=self._direct_state.shape,
                amplitude=self._direct_state.amplitude,
                center=self._direct_state.center,
            )
        return phase_to_position(self._stroke_phase)

    def current_position(self) -> int:
        return self._compute_position()

    @property
    def stroke_phase(self) -> float:
        return self._stroke_phase

    def maybe_send(self, phase: float, now: float) -> None:
        # Accumulate continuous stroke phase, detecting wraps.
        delta = phase - self._last_phase
        if delta < -0.5:
            delta += 1.0
        self._stroke_phase += max(0.0, delta)
        self._last_phase = phase

        elapsed = now - self._last_send_time
        if elapsed < self._min_interval:
            return
        interval_ms = max(1, min(9999, round(elapsed * 1000)))
        position = self._compute_position()
        # A stroke tick asks the device to be at the next phase position in the
        # time one tick takes, which is right while Genau has been driving all
        # along and is a slam the moment it has just taken the device back: the
        # device is where a funscript left it, and the phase has run on without
        # it.  The glide floors the interval for its own length, so these ticks
        # re-aim at a target the device is always given long enough to reach.
        self._sink.send(format_tcode_command(
            "L0", position, self._glide.interval_ms(interval_ms, now)))
        self._last_send_time = now

    def close(self) -> None:
        self._sink.close()
