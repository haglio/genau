"""The launch smoke test: everything each launcher's ``-m`` imports, imported.

Three apps ship from this repo -- Genau, Nau and Genau VR -- each with its own
shortcut, its own ``.vbs``, and its own package, and the suite can be entirely
green while any of their icons does nothing. Every other test here runs under
``tests/conftest.py``, which moves this tree to the front of ``sys.path`` before
collection precisely because a sibling worktree or an ancestor directory would
otherwise answer for it; the launchers have no such help, so what resolves at
launch is not what resolves under pytest. And they run ``pythonw``, which has no
console: an import that fails writes its traceback nowhere and the app simply
never appears.

So this drives each launch's import phase the way its launcher does: a fresh
interpreter, this repo as the working directory, no inherited ``PYTHONPATH``.

The walk that reads those imports off the AST and the three assertions that
replay them are ``app_support.launch_smoke``: seven repos carried a copy of the
same 200 lines, drifting. What stays here is the half that is this repo's --
the three launches, the files each one executes, and how a ``.vbs`` starts an
interpreter.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from app_support.launch_smoke import (
    assert_an_unresolvable_import_is_caught,
    assert_every_import_resolves,
    assert_the_walk_reached,
    launch_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# One per shortcut on the desktop: the package its .vbs runs, the launcher
# itself, and a module the launch reaches only from inside main() -- asserted
# present, so a walk that silently found nothing cannot pass as a clean launch.
LAUNCHES = (
    ("genau", "launch.vbs", "genau.state"),
    ("nau", "launch_nau.vbs", "nau.session"),
    ("genau_vr", "launch_vr.vbs", "genau_vr.vr_session"),
)


def _launch_files(package: str):
    """The two files ``-m <package>`` runs: the entrypoint, and the module
    holding main(). Every helper main() calls lives in the second."""
    return (
        REPO_ROOT / package / "__main__.py",
        REPO_ROOT / package / "app.py",
    )


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way the ``.vbs`` launchers run their apps.

    Each sets this repo as the working directory and runs the venv's pythonw
    with nothing else, so the working directory is the whole path story -- any
    ``PYTHONPATH`` a developer or pytest happens to be carrying is dropped,
    because the shortcut does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["SDL_VIDEODRIVER"] = "dummy"  # pygame must not open a window to import

    return subprocess.run(
        [sys.executable, "-c", "\n".join(statements)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_the_launch_imports_everything_it_names(package, launcher, lazy_module):
    """Failing here means that shortcut does nothing: pythonw has no console, so
    the traceback from a failed import goes nowhere at all."""
    assert_every_import_resolves(
        _run_the_launchs_way, launch_imports(package, _launch_files(package)))


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_the_walk_reaches_the_imports_buried_in_main(package, launcher, lazy_module):
    """The guard above is only worth anything if the walk found the lazy ones."""
    assert_the_walk_reached(
        launch_imports(package, _launch_files(package)), [lazy_module])


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_a_launch_import_that_cannot_resolve_fails_here(package, launcher, lazy_module):
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    assert_an_unresolvable_import_is_caught(
        _run_the_launchs_way, launch_imports(package, _launch_files(package)),
        lazy_module)


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_the_launcher_runs_its_package_from_this_repo_on_the_venv(package, launcher, lazy_module):
    """A python off PATH finds the repo directory as a namespace package instead
    of the editable install and dies while importing. The working directory is
    what this test's ``cwd`` mirrors, so a launcher that stopped setting it
    would leave this checking a fiction."""
    text = (REPO_ROOT / launcher).read_text(encoding="utf-8", errors="replace")

    assert ".venv\\Scripts\\pythonw.exe" in text
    assert f"-m {package}" in text
    assert "shell.CurrentDirectory = scriptDir" in text
