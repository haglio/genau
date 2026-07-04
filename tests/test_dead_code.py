"""Dead-code regression test using vulture."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
GENAU_DIR = _ROOT / "genau"
NAU_DIR = _ROOT / "nau"
WHITELIST = _ROOT / "vulture_whitelist.py"


def test_no_dead_code():
    cmd = [
        sys.executable, "-m", "vulture",
        str(GENAU_DIR),
        str(NAU_DIR),
        str(WHITELIST),
        "--min-confidence", "60",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"Vulture found dead code:\n{result.stdout.strip()}\n{result.stderr.strip()}"
    )
