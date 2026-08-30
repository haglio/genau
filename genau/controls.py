"""What a control can reach.

Genau's controls are spoken to from three places -- a verb in ``genau_cmd.txt``,
a key in the window, a press on the console -- and every one of them has to be
able to move the same handful of things: the hand's own state, the cruise stack,
the clip advance, the two boxes an orchestrator flips, the clip sequence.

Passing those one at a time is what made adding a control a four-to-six file
edit: a keyword parameter on the dispatcher, another on the refresh controller,
an attribute to store it and a line to hand it on.  They travel together here
instead, built once where the app is wired and handed whole.

Optional means *this build did not wire it* -- a Genau launched without a cruise
stack, a test that only cares about the clip sequence.  A verb whose collaborator
is absent is refused and logged rather than half-acted-on, which is the behaviour
:func:`genau.runtime_commands.apply_runtime_command` documents.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, MutableMapping

from player_core.cruise_control import CruiseControlState
from player_core.direct_control import DirectControlState

from .clip_advance import ClipAdvanceState
from .engine import PlaybackEngine


@dataclass
class GenauControls:
    """Everything one command, key or console press may move."""

    engine: PlaybackEngine
    rh_paused: MutableMapping[str, bool]
    step_clip: Callable[[int], None]
    discard_clip: Callable[[], None] | None = None
    direct_state: DirectControlState | None = None
    cruise_control_state: CruiseControlState | None = None
    set_stroke_phase: Callable[[float], None] | None = None
    clip_advance_state: ClipAdvanceState | None = None
    stop_event: threading.Event | None = None
    hud_state: MutableMapping[str, bool] | None = None
    display_state: MutableMapping[str, bool] | None = None
    set_volume: Callable[[int, bool], None] | None = None
    reorder_clips: Callable[[bool], None] | None = None
