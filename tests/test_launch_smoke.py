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

The statements come off the AST of the files each launch executes rather than a
list maintained here, because a hand-written list is exactly what would drift:
the next lazy import added to a ``main()`` would not be in it, and the guard
would quietly stop covering the thing it was written for. They are replayed as
whole ``from X import a, b`` statements, not as ``import X``, so a symbol the
launch names but the module no longer defines fails here too.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys

import pytest

from pathlib import Path

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

# Only these two. A broad ``except Exception`` around a launch body is an error
# *reporter* -- it puts a dialog on screen or writes a crash log -- so an import
# inside it is required, not optional: it failing is exactly the launch failure
# this file exists to catch.
_TOLERATED_BY = {"ImportError", "ModuleNotFoundError"}


# --------------------------------------------------------------------------
# What the launch imports
# --------------------------------------------------------------------------

def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING:`` bodies are never executed, at launch or anywhere."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _tolerates_a_missing_module(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:  # bare except -- catches everything, promises nothing
            return False
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        if any(isinstance(n, ast.Name) and n.id in _TOLERATED_BY for n in caught):
            return True
    return False


def _optional_imports(tree: ast.Module) -> set[int]:
    """Imports whose absence the module already handles, so the launch survives
    them and this test must not insist on them."""
    optional: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            body = node.body
        elif isinstance(node, ast.Try) and _tolerates_a_missing_module(node.handlers):
            body = node.body
        else:
            continue
        for statement in body:
            for inner in ast.walk(statement):
                optional.add(id(inner))
    return optional


def _render(node: ast.Import | ast.ImportFrom, package: str) -> str:
    """The import statement as the launch executes it, relative made absolute.

    Every launch file here sits at the top of its package, so a relative import
    is never deeper than one level.
    """
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    if isinstance(node, ast.Import):
        return f"import {names}"
    assert node.level <= 1, f"unexpected relative import depth in {package}"
    module = node.module or ""
    if node.level:
        module = f"{package}.{module}" if module else package
    return f"from {module} import {names}"


def _is_a_compiler_directive(node: ast.Import | ast.ImportFrom) -> bool:
    """``from __future__ import ...`` loads no module -- it is a flag to the
    compiler, and it is only legal at the top of a file, so replaying it among
    the others is a SyntaxError rather than a check of anything."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _launch_imports(package: str, launch_files) -> list[str]:
    statements: list[str] = []
    for path in launch_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        optional = _optional_imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in optional or _is_a_compiler_directive(node):
                continue
            statements.append(_render(node, package))
    return statements


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
    result = _run_the_launchs_way(_launch_imports(package, _launch_files(package)))

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_the_walk_reaches_the_imports_buried_in_main(package, launcher, lazy_module):
    """The guard above is only worth anything if the walk found the lazy ones."""
    found = "\n".join(_launch_imports(package, _launch_files(package)))

    assert lazy_module in found, f"the launch imports {lazy_module}; the walk missed it"


@pytest.mark.parametrize("package,launcher,lazy_module", LAUNCHES)
def test_a_launch_import_that_cannot_resolve_fails_here(package, launcher, lazy_module):
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    statements = [
        *_launch_imports(package, _launch_files(package)),
        f"from {lazy_module} import NoSuchSymbol",
    ]

    result = _run_the_launchs_way(statements)

    assert result.returncode != 0
    assert "NoSuchSymbol" in result.stderr


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
