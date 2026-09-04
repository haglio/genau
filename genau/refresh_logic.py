from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SharedStateSnapshot:
    auto_active: bool
    raw_bpm: float | None
    sync_pulse_id: int


def read_shared_state_snapshot(state) -> SharedStateSnapshot:
    with state.lock:
        return SharedStateSnapshot(
            auto_active=state.auto_active,
            raw_bpm=state.raw_bpm,
            sync_pulse_id=state.sync_pulse_id,
        )


def display_index_for_phase(
    *,
    phase: float,
    frame_count: int,
    auto_active: bool,
    current_frame_index: int | None,
) -> int:
    logical_index = int(phase * frame_count)
    if logical_index >= frame_count:
        logical_index = frame_count - 1

    display_index = (frame_count - 1) - logical_index
    if not auto_active and current_frame_index is not None:
        return current_frame_index
    return display_index


@dataclass(frozen=True)
class Beat:
    """What the engine is told this tick, and which of the two decided it.

    Genau plays two ways.  Under the broker it follows a BPM and a sync pulse
    published over UDP and a paused flag read off a file; on its own it follows
    its own hand, whose speed *is* the BPM and whose stopping *is* the pause.
    The four numbers below are the same four either way, which is what lets one
    engine serve both -- and ``robot_hand_active`` is which of the two answered, the
    fact the rest of the tick branches on.
    """

    robot_hand_active: bool
    auto_active: bool
    raw_bpm: float | None
    paused: bool
    sync_pulse_id: int
