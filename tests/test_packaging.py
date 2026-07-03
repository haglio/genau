from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_all_app_packages_are_declared_for_installation():
    """Every launchable package must be importable from the installed
    distribution, not just from a repo-root CWD.

    Fun Time launches `python -m nau` (and `-m genau`) via this project's
    venv without setting a working directory. Setuptools' automatic
    flat-layout discovery refuses multiple top-level packages, so unless
    they are declared explicitly the editable install maps only whichever
    package it guessed — which is how `python -m nau` silently broke.
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
    for package, pattern in (("genau", "genau*"), ("nau", "nau*")):
        assert pattern in include, (
            f"pyproject must declare {pattern!r} in "
            f"[tool.setuptools.packages.find] include so {package!r} is "
            "importable from the installed distribution"
        )
