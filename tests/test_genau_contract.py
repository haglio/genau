"""The flicks-folder layout Genau promises the apps that fill it, held to the engine's.

Evolver delivers flicks into the folder Genau plays from and reads the pile a
condemned flick moves to; it holds both to ``genau_contract.json`` at this
checkout's root (its own tests/test_genau_contract.py).  The layout itself is
player_core's, which the Main Player runs Genau on, so the document is held here
to ``player_core.flick_folder`` and rewritten by hand when that moves.  Each
section is published under its name from before the rename as well, for the
checkouts of Evolver and Genaumacher that still read that one.
"""
from __future__ import annotations

import json
from pathlib import Path

from player_core.flick_folder import flat_flicks_in, vr_flicks_in, weird_dir_for_flicks_folder

CONTRACT = Path(__file__).resolve().parent.parent / "genau_contract.json"
SECTIONS_BEFORE_THE_RENAME = {
    "inside_the_flicks_folder": "inside_the_clips_folder",
    "beside_the_flicks_folder": "beside_the_clips_folder",
}


def test_the_published_layout_is_the_engines():
    flicks = Path("C:/a-library/flicks")
    layout = {
        "inside_the_flicks_folder": {
            "flat": flat_flicks_in(flicks).name,
            "vr": vr_flicks_in(flicks).name,
        },
        "beside_the_flicks_folder": {"condemned": weird_dir_for_flicks_folder(flicks).name},
    }

    published = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert published == {
        **layout,
        **{SECTIONS_BEFORE_THE_RENAME[name]: section for name, section in layout.items()},
    }
