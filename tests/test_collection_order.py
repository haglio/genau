"""The gate runs this suite in more than one order, and this pins the switch.

A test that leans on the one beside it is green until something renames a file,
and then it is red in a commit that had nothing to do with it -- so the gate
collects the suite a second time in another order, and `conftest.py` decides
which.  The end-to-end checks matter more than they look: a hook pytest never
calls is precisely how a suite ends up with a fixture file nothing loads.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import conftest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = PROJECT_ROOT / "tests" / "test_genau_pygame_view.py"


def _collected(**order_env: str) -> list[str]:
    """The test ids `pytest --collect-only` reports for one file, in order.

    The child is given exactly the order this call names -- the gate's own legs
    run with one of these set, and inheriting it would make every comparison
    here a comparison of two identical reorderings.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("TEST_COLLECTION_ORDER", "TEST_COLLECTION_SEED")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(SAMPLE),
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=PROJECT_ROOT, env={**env, **order_env},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line for line in result.stdout.splitlines() if "::" in line]


def test_the_suite_collects_in_the_order_it_is_written_when_nothing_asks_otherwise():
    declared = [line.split("def ")[1].split("(")[0]
                for line in SAMPLE.read_text(encoding="utf-8").splitlines()
                if line.startswith("def test_")]

    assert [test_id.split("::")[-1] for test_id in _collected()] == declared


def test_reverse_collects_the_same_tests_back_to_front():
    assert _collected(TEST_COLLECTION_ORDER="reverse") == list(reversed(_collected()))


def test_shuffle_moves_the_tests_and_repeats_itself_from_the_seed():
    forward = _collected()
    shuffled = _collected(TEST_COLLECTION_ORDER="shuffle")

    assert sorted(shuffled) == sorted(forward)
    assert shuffled != forward
    assert shuffled == _collected(TEST_COLLECTION_ORDER="shuffle")
    assert shuffled != _collected(TEST_COLLECTION_ORDER="shuffle",
                                  TEST_COLLECTION_SEED="1")


def test_an_order_nobody_recognizes_is_refused_rather_than_ignored(monkeypatch):
    """A typo in the gate must not read as a second green run of the first order."""
    monkeypatch.setenv("TEST_COLLECTION_ORDER", "reversed")

    with pytest.raises(pytest.UsageError, match="reversed"):
        conftest.pytest_collection_modifyitems(items=[])
