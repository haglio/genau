"""How far the OpenXR stack got, and what to tell the user when it stopped.

This is the answer, not the asking: an enum, a small frozen record, and the
wording that goes in the popup.  It names no platform and imports nothing that
has one, which is the point — GenauVR launches hidden from a shortcut, so what
the user sees when VR is missing is all they get, and a module that could only
be imported where VR is present would be exactly the wrong place to keep it.

``vr_runtime`` does the asking and re-exports these, so ``app.py`` and every
existing caller keep reading them from where they always did.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

APP_NAME = "GenauVR"

_UNKNOWN_FAILURE = "VR could not be started."

_EXPLANATIONS = {
    "no_headset": (
        "No VR headset is answering.\n\n"
        "Power the headset on and connect it, then start GenauVR again."
    ),
    "no_runtime": (
        "No OpenXR runtime is available.\n\n"
        "Install or start your VR runtime (PimaxXR, SteamVR), then start "
        "GenauVR again."
    ),
}


class Readiness(Enum):
    """How far the OpenXR stack got before it stopped answering."""

    READY = "ready"
    NO_RUNTIME = "no_runtime"
    NO_HEADSET = "no_headset"
    FAILED = "failed"


@dataclass(frozen=True)
class Probe:
    """What a single look at the OpenXR stack found."""

    readiness: Readiness
    detail: str = ""


def explain(result: Probe) -> str:
    """The popup text for a probe that did not end in a headset.

    Falls back rather than raising on a readiness it has no wording for: this
    runs on the error path, and a crash here is the silent failure it replaces.
    """
    lead = _EXPLANATIONS.get(result.readiness.value, _UNKNOWN_FAILURE)
    return f"{lead}\n\nDetail: {result.detail}"
