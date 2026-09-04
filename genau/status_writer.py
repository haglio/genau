from __future__ import annotations

from pathlib import Path

from player_core.cruise_control import CruiseControlState
from player_core.robot_hand import RobotHandState

from .clip_advance import ClipAdvanceState
from .limits import control_limits


def build_status_text(
    hand: RobotHandState,
    cruise: CruiseControlState,
    *,
    clip_advance: ClipAdvanceState | None = None,
    hud_active: bool = False,
    clip: Path | None = None,
) -> str:
    limits = control_limits(hand)
    advance = clip_advance or ClipAdvanceState()
    return (
        f"cruise={'1' if cruise.active else '0'}\n"
        f"locked={'1' if advance.locked else '0'}\n"
        # Which clip is up.  Everything else here describes the hand, which an
        # orchestrator set and therefore already knows; the clip it does not, and
        # without it a reopened session can only start Genau at the top of a
        # freshly scanned folder.  Empty until the first clip is on screen.
        f"clip={clip if clip is not None else ''}\n"
        f"shape={hand.shape.value}\n"
        f"amp_at_max={'1' if limits.amp_at_max else '0'}\n"
        f"amp_at_min={'1' if limits.amp_at_min else '0'}\n"
        f"ctr_at_max={'1' if limits.ctr_at_max else '0'}\n"
        f"ctr_at_min={'1' if limits.ctr_at_min else '0'}\n"
        f"spd_at_max={'1' if limits.spd_at_max else '0'}\n"
        f"spd_at_min={'1' if limits.spd_at_min else '0'}\n"
        f"hud={'1' if hud_active else '0'}\n"
    )


def write_status_file(
    path: Path,
    hand: RobotHandState,
    cruise: CruiseControlState,
    *,
    clip_advance: ClipAdvanceState | None = None,
    hud_active: bool = False,
    clip: Path | None = None,
) -> bool:
    text = build_status_text(
        hand, cruise, clip_advance=clip_advance, hud_active=hud_active, clip=clip,
    )
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
