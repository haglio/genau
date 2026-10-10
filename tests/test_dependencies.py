"""What this repo needs is what its pyproject says, in each of the ways it says it.

This repo holds no code of its own: it is the venv Fun Time's Main Funestra runs
out of, so what it declares is what it imports, and what is checked
here is the declaring -- a version nobody bounded, a sibling nobody pinned, a
Python floor no run proves.  The gates are the family's
(``app_support.dependencies``); what is here is which trees to read.
"""
from __future__ import annotations

from pathlib import Path

from app_support.dependencies import (
    assert_every_dependency_is_bounded,
    assert_every_import_is_declared,
    assert_every_sibling_is_declared,
    assert_every_sibling_is_pinned,
    assert_the_declared_floor_is_the_one_the_gate_runs,
)

ROOT = Path(__file__).resolve().parent.parent
TREES = [ROOT / "tests", ROOT / "tools"]


def test_every_third_party_import_is_declared():
    assert_every_import_is_declared(ROOT, TREES, ROOT / "pyproject.toml")


def test_every_requirement_has_an_upper_bound():
    assert_every_dependency_is_bounded(ROOT / "pyproject.toml")


def test_every_sibling_this_repo_needs_is_declared():
    assert_every_sibling_is_declared(ROOT, TREES, ROOT / "pyproject.toml")


def test_every_sibling_is_named_at_a_tag():
    assert_every_sibling_is_pinned(ROOT / "pyproject.toml")


def test_the_declared_floor_is_the_one_the_gate_runs():
    assert_the_declared_floor_is_the_one_the_gate_runs(
        ROOT / "pyproject.toml", ROOT / ".github" / "workflows" / "merge-gate.yml")
