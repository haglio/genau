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
from player_core.funscript import HANDOFF_RAMP_MS

if TYPE_CHECKING:
    from player_core.direct_control import DirectControlState

# The rise only exists when there is a gap to climb: at full amplitude the
# stroke's floor IS the park, and holding the swing there would delay a resume
# that already starts from where the device sits.  Two percent of the travel,
# the trace's own park epsilon.
_RISE_SKIP_BELOW = 200


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
        # The rise out of the park: 1.0 is the stroke's own motion; anything
        # lower scales the held phase-0 position, so the device climbs from the
        # park to the stroke's floor before the swing begins — the mirror of
        # the glide down that ends Genau's turn.  A takeover zeroes it; the
        # clock starts on the first send after that.
        self._rise = 1.0
        self._rise_started: float | None = None
        # Where the device was when this sender last handed it over, in T-Code
        # units; None while it holds the device.  Published with the readout —
        # see :meth:`hand_over`.
        self._let_go_position: int | None = None

    def take_over(self) -> None:
        """Genau has the device again: resume the stroke from the foot of its
        swing, and ease onto it.

        The funscript's turn leaves the device at its park, and the frozen
        phase could be anywhere in the cycle — resuming there aimed the first
        commands at whatever height the swing happened to freeze at, a lunge
        across most of the range.  From the bottom, and through the rise: the
        stroke's floor can sit well above the park (amplitude under 100, a
        raised center), and starting the swing there jumped the device across
        the gap — so the swing holds while the device climbs park-to-floor over
        :data:`~player_core.funscript.HANDOFF_RAMP_MS`, then begins.  A
        floor already on the park skips the climb; the stroke starts at once,
        as it always did at full amplitude.
        """
        self.rest_at_bottom()
        if self._compute_position() > _RISE_SKIP_BELOW:
            self._rise = 0.0
            self._rise_started = None
            # let_go stays published through the climb: it means "my published
            # wave is the frozen phase-0 one, not yet running", and through the
            # rise that is still true.  Cleared when the climb completes and
            # the wave actually starts — the readers that re-anchor on that
            # edge (the trace's descent top after an OmniPause realign) need
            # the edge to land when the realigned wave is finally live.
        else:
            # No gap to climb — the stroke starts at once, so the publish is
            # live from this tick — and a climb this takeover interrupted must
            # not leave its fraction scaling every position from here on.
            self._rise = 1.0
            self._let_go_position = None
        self._glide.begin()

    def hand_over(self) -> None:
        """Genau is losing the device: remember where, and let go.

        The height the swing was at is latched BEFORE the phase rests, because
        resting destroys it — a paused sender publishes the stroke it will
        resume with, not the position it stopped at — and it is the one number
        the trace cannot recompute when it draws the descent.  Nothing is sent:
        the driver taking the device owns walking it down (its first park is
        the handoff ramp), and a second writer's glide here was superseded
        within a tick and only bent the descent.
        """
        self._let_go_position = self.current_position()
        self.rest_at_bottom()

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
        """Where the device is being sent right now — scaled by the rise while
        it is still climbing out of the park, so the published readout and the
        dot riding it follow the climb rather than sitting on the floor."""
        return round(self._compute_position() * self._rise)

    @property
    def stroke_phase(self) -> float:
        return self._stroke_phase

    @property
    def let_go_position(self) -> int | None:
        """Where the device was handed over, in T-Code units — None while this
        sender still has it."""
        return self._let_go_position

    def maybe_send(self, phase: float, now: float) -> None:
        if self._rise < 1.0:
            # Climbing out of the park: the swing holds at the floor (phase 0)
            # while the device rises to it, so the phase is tracked but not
            # advanced, and the sent position is the floor scaled by how far
            # the climb has come.
            if self._rise_started is None:
                self._rise_started = now
            self._rise = min(1.0, (now - self._rise_started) / (HANDOFF_RAMP_MS / 1000))
            if self._rise >= 1.0:
                # The climb is done and the wave runs from here: the publish is
                # live again, which is what clearing let_go announces.
                self._let_go_position = None
            self._last_phase = phase
        else:
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
        position = round(self._compute_position() * self._rise)
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
