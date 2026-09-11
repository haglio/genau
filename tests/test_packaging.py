from __future__ import annotations

import tomllib
from pathlib import Path

from app_support.dependencies import assert_every_dependency_is_imported

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"


def test_all_app_packages_are_declared_for_installation():
    """Every launchable package must be importable from the installed
    distribution, not just from a repo-root CWD.

    Fun Time launches `python -m genau` via this project's venv without
    setting a working directory, so the package has to be declared for the
    editable install rather than left to setuptools' guess — which is how a
    launch once silently broke.
    """
    with _PYPROJECT.open("rb") as fp:
        pyproject = tomllib.load(fp)

    include = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )
    assert "genau*" in include, (
        "pyproject must declare 'genau*' in [tool.setuptools.packages.find] "
        "include so 'genau' is importable from the installed distribution"
    )


def test_every_declared_runtime_dependency_is_imported_somewhere():
    """A dependency nothing imports is fetched by every install and every CI run.

    `pyserial` was one: Genau reaches the OSR2 over UDP through the broker, and
    it is the broker repo that talks to the serial port and declares the package
    itself.
    """
    assert_every_dependency_is_imported(
        _ROOT, [_ROOT / "genau", _ROOT / "tests", _ROOT / "tools"], _PYPROJECT)
