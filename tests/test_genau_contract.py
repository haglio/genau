"""The clips-folder layout Genau promises the apps that fill it, held to the engine's.

Evolver delivers clips into the folder Genau plays from and reads the pile a
condemned clip moves to; it holds both to ``genau_contract.json`` at this
checkout's root (its own tests/test_genau_contract.py).  The layout itself is
player_core's, which the Main Player runs Genau on, so the document is held here
to ``player_core.clip_folder`` and rewritten by hand when that moves.
"""
from __future__ import annotations

import json
from pathlib import Path

from player_core.clip_folder import flat_clips_in, vr_clips_in, weird_dir_for_clips_folder

CONTRACT = Path(__file__).resolve().parent.parent / "genau_contract.json"


def test_the_published_layout_is_the_engines():
    clips = Path("C:/a-library/clips")

    published = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert published == {
        "inside_the_clips_folder": {
            "flat": flat_clips_in(clips).name,
            "vr": vr_clips_in(clips).name,
        },
        "beside_the_clips_folder": {"condemned": weird_dir_for_clips_folder(clips).name},
    }
