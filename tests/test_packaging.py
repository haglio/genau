from __future__ import annotations

import ast
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


def test_every_declared_runtime_dependency_is_imported_somewhere():
    """A dependency nothing imports is fetched by every install and every CI run.

    `pyserial` was one: Genau reaches the OSR2 over UDP through the broker,
    and it is the broker repo that talks to the serial port and declares the
    package itself.
    """
    # Only the ones whose import name is not the distribution name.
    import_names = {"opencv-python": "cv2", "pillow": "PIL", "pygame-ce": "pygame"}
    with _PYPROJECT.open("rb") as fp:
        declared = tomllib.load(fp)["project"]["dependencies"]

    tree = Path(__file__).resolve().parent.parent
    imported: set[str] = set()
    for path in tree.rglob("*.py"):
        if any(part in {".venv", "__pycache__", ".claude"}
               for part in path.relative_to(tree).parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split(".")[0])
    unimported = [
        name for name in declared
        if import_names.get(name, name.replace("-", "_")) not in imported
    ]

    assert not unimported, f"declared and never imported: {unimported}"
