from __future__ import annotations

from pathlib import Path

from .clip_advance import ClipAdvanceState
from .cruise_control import CruiseControlState
from .direct_control import (
    MAX_SPEED,
    MIN_SPEED,
    DirectControlState,
)


def build_status_text(
    direct: DirectControlState,
    cruise: CruiseControlState,
    *,
    clip_advance: ClipAdvanceState | None = None,
    hud_active: bool = False,
) -> str:
    half = direct.amplitude // 2
    ctr_lo = half
    ctr_hi = 100 - half
    advance = clip_advance or ClipAdvanceState()
    return (
        f"cruise={'1' if cruise.active else '0'}\n"
        f"locked={'1' if advance.locked else '0'}\n"
        f"shape={direct.shape.value}\n"
        f"amp_at_max={'1' if direct.amplitude >= 100 else '0'}\n"
        f"amp_at_min={'1' if direct.amplitude <= 0 else '0'}\n"
        f"ctr_at_max={'1' if direct.center >= ctr_hi else '0'}\n"
        f"ctr_at_min={'1' if direct.center <= ctr_lo else '0'}\n"
        f"spd_at_max={'1' if direct.speed >= MAX_SPEED else '0'}\n"
        f"spd_at_min={'1' if direct.speed <= MIN_SPEED else '0'}\n"
        f"hud={'1' if hud_active else '0'}\n"
    )


def write_status_file(
    path: Path,
    direct: DirectControlState,
    cruise: CruiseControlState,
    *,
    clip_advance: ClipAdvanceState | None = None,
    hud_active: bool = False,
) -> bool:
    text = build_status_text(
        direct, cruise, clip_advance=clip_advance, hud_active=hud_active,
    )
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
