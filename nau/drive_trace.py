"""What the device is about to be asked to do, and by whom — the trace's model.

The drive readout draws one line across a stretch of time running forward from
the playhead.  Who is driving over that stretch is not one answer: a funscript
drives while it is scripting and Genau drives the gaps, and the boundary between
them is somewhere *inside* the span most of the time.  This walks the span
deciding per sample, so the line can be drawn green where the script has it and
blue where the stroke does, joined at the moment the device changes hands.

That boundary is not a guess.  Fun Time hands the OSR2 over on exactly the rule
used here — the script has it wherever it is not resting — so what the trace
shows ahead of the seam is the seam that is coming.

Kept out of :mod:`nau.app` and free of Pillow, like :mod:`nau.console` is, so the
shape of the picture is testable without a window or a font.
"""
from __future__ import annotations

from dataclasses import replace

from genau.drive_hud import (
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_GENAU,
    DRIVEN_BY_NOTHING,
    POSITION_MAX,
    TRACE_SAMPLES,
    DriveHud,
)


def drive_readout(
    published: DriveHud | None,
    *,
    script,
    position_ms: int,
    speed: float = 1.0,
    genau_behind: bool,
    osr2_has_script: bool,
) -> DriveHud:
    """The readout to draw, folding the funscript's own shape into it.

    *published* is Genau's readout as it last said it, or None where there is no
    Genau behind the screen (Nau's own mode).  *genau_behind* says whether Genau
    is there to take the gaps; *osr2_has_script* is whether a script has the
    device *now*, which is what decides where the position marker comes from.

    The span is Genau's own — it publishes the number with its trace — scaled by
    the playback rate, because the trace covers wall-clock time and at double
    speed twice as much of the script goes past in it.  Sampling the script on
    its own fixed grid (:meth:`player_core.funscript.Funscript.trace`) is what
    keeps the shape still: resampled from the playhead every frame, every peak
    landed somewhere slightly different and the line boiled in place.
    """
    base = published or DriveHud()
    if script is None:
        return base
    span_ms = round(base.trace_seconds * 1000 * speed)
    step = span_ms / max(1, TRACE_SAMPLES - 1)
    scripted = script.trace(position_ms, span_ms, TRACE_SAMPLES)
    if len(scripted) != TRACE_SAMPLES:
        return base
    # Whoever has the device where the script does not.  In Hybrid that is Genau's
    # own stroke, drawn forward from the phase it is parked on — the very stroke it
    # will resume with.  In Nau nobody does: the script's driver rests the device,
    # so the picture is the floor rather than a stroke that is not coming.
    idle_driver = DRIVEN_BY_GENAU if genau_behind else DRIVEN_BY_NOTHING
    stroke = base.waveform if len(base.waveform) == TRACE_SAMPLES else None

    values: list[float] = []
    marks: list[tuple[int, str]] = []
    for index in range(TRACE_SAMPLES):
        driving = not script.is_resting_at(round(position_ms + index * step))
        values.append(
            scripted[index] if driving
            else (stroke[index] if stroke is not None else 0.0))
        who = DRIVEN_BY_FUNSCRIPT if driving else idle_driver
        if not marks or marks[-1][1] != who:
            marks.append((index, who))
    return replace(
        base,
        waveform=tuple(values),
        # One mark means one driver over the whole span, which is what an empty
        # ``segments`` already says — and saying it that way keeps the readout
        # comparing equal to itself, so the panel is not repainted for a change
        # that is only in how the same picture was described.
        segments=tuple(marks) if len(marks) > 1 else (),
        # The dot down the edge is where the device is, and while a script has it
        # that is wherever the script says — not the stroke position Genau
        # published, which is a stroke nothing is sending.
        position=(round(script.position_at(position_ms) / 100 * POSITION_MAX)
                  if osr2_has_script else base.position),
    )
