"""The suite must test the tree it lives in, whatever directory it is run from.

Every agent works in a `.claude/worktrees/<name>/` copy of this repo, so several
trees carrying the same package names sit on one machine at once.  `python -m
pytest` puts the *current directory* on `sys.path` ahead of the editable
install's entry for the real checkout, so a run started from one tree against
another's tests imports the wrong `nau`/`genau`.  Loud when the two have drifted
enough to break an import; silent when they have not, which is the expensive
one — a green suite that says nothing about the code you actually have.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import genau
import nau

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_the_packages_under_test_are_this_trees():
    """The cheap half: whatever the path ended up as, the two packages this
    suite is about came out of the tree the suite lives in."""
    for package in (nau, genau):
        assert Path(package.__file__).resolve().parent.parent == PROJECT_ROOT, (
            f"{package.__name__} came from {package.__file__}, not {PROJECT_ROOT}"
        )


def _decoy_tree(tmp_path: Path) -> Path:
    """A directory carrying this repo's two package names and nothing real.

    Its `nau.library` has none of the real one's names, so a decoy that wins
    cannot pass by accident.
    """
    for package in ("nau", "genau"):
        (tmp_path / package).mkdir()
        (tmp_path / package / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "nau" / "library.py").write_text(
        '"""Decoy: importing anything real from here fails."""\n', encoding="utf-8",
    )
    return tmp_path


def test_the_suite_imports_its_own_tree_from_a_foreign_directory(tmp_path: Path):
    """The half that needs a subprocess: run one of this tree's tests with the
    working directory inside a decoy that carries the same package names.

    Without the pin the decoy wins — it is the cwd, and the cwd outranks the
    editable install's path entry — and the run dies collecting.
    """
    decoy = _decoy_tree(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         str(PROJECT_ROOT / "tests" / "test_nau_library.py"),
         "-q", "-p", "no:cacheprovider"],
        cwd=decoy, capture_output=True, text=True,
    )

    assert result.returncode == 0, (
        f"the decoy tree at {decoy} was imported instead of {PROJECT_ROOT}\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_a_tree_already_imported_before_the_pin_is_named_outright(tmp_path: Path):
    """The path fix cannot undo an import that already happened, so the guard
    behind it has to say which tree won rather than let the suite run on it.

    Reached by a plugin that imports `nau` before conftest does — `sys.modules`
    then holds the decoy's, whatever the path is rearranged to afterwards.
    """
    decoy = _decoy_tree(tmp_path)
    (decoy / "early.py").write_text("import nau\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         str(PROJECT_ROOT / "tests" / "test_nau_library.py"),
         "-q", "-p", "no:cacheprovider", "-p", "early"],
        cwd=decoy, env={**os.environ, "PYTHONPATH": str(decoy)},
        capture_output=True, text=True,
    )

    # A conftest that raises is a collection error, which pytest reports on
    # stderr, so the message is looked for across both streams.
    reported = result.stdout + result.stderr
    assert result.returncode != 0, "the suite ran on the decoy's code"
    assert str(decoy) in reported, reported
    assert str(PROJECT_ROOT) in reported, reported
