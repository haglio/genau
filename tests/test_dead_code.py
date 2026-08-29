"""Dead-code regression test using vulture."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
GENAU_DIR = _ROOT / "genau"
NAU_DIR = _ROOT / "nau"
WHITELIST = _ROOT / "vulture_whitelist.py"

PACKAGE_DIRS = (GENAU_DIR, NAU_DIR, _ROOT / "genau_vr")


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


# The three ruff rules that name dead code and nothing else: an import
# nothing uses, a redefinition that shadows the first, a local assigned and
# never read. Vulture sees none of them -- it treats an import as used when
# the same name appears in any other file it scans, so a stray `import json`
# in one module hides behind a real one in its neighbour.
_DEAD_CODE_LINT_RULES = "F401,F811,F841"


# One finding is held open on purpose. tests/test_win32.py imports MagicMock
# and does not yet use it: a parked bug-fix branch adds the two COM-apartment
# cases that do, and taking the import out here would land them broken.
# Delete this entry once that branch has landed -- the gate then covers the
# file like every other.
_HELD_OPEN = ("tests/test_win32.py:9:", )


def test_no_dead_imports_or_unread_locals():
    cmd = [
        sys.executable, "-m", "ruff", "check",
        "--select", _DEAD_CODE_LINT_RULES,
        "--output-format", "concise",
        str(GENAU_DIR), str(NAU_DIR), str(_ROOT / "genau_vr"),
        str(_ROOT / "tools"), str(_ROOT / "tests"),
    ]
    result = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    reported = [
        line for line in result.stdout.splitlines()
        if ": F" in line and not line.startswith(_HELD_OPEN)
    ]

    assert not reported, "ruff found dead code:\n" + "\n".join(reported)


def _attribute_names_read_anywhere() -> set[str]:
    """Every ``x.<name>`` read in the tree, plus every string literal.

    The string literals are there so a ``getattr(obj, "thing")`` or a name
    looked up out of a dict counts as a read; the point of this scan is to
    be sure before deleting, not to find every last one.
    """
    names: set[str] = set()
    for path in _ROOT.rglob("*.py"):
        # Relative parts: this repo is worked in a git worktree under
        # .claude/, so an absolute-path check would exclude the whole tree.
        if any(part in {".venv", "__pycache__", ".claude"}
               for part in path.relative_to(_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def _stored_but_unread_parameters() -> list[str]:
    """``self.x = x`` in an ``__init__`` where nothing ever reads ``.x``.

    Two conditions, both required, so an attribute a collaborator reads from
    outside its class does not read as dead: unread by any method of its own
    class, and unread under that name anywhere in the tree.
    """
    read_anywhere = _attribute_names_read_anywhere()
    found: list[str] = []
    for package in PACKAGE_DIRS:
        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
                init = next(
                    (f for f in cls.body
                     if isinstance(f, ast.FunctionDef) and f.name == "__init__"),
                    None,
                )
                if init is None:
                    continue
                params = {a.arg for a in init.args.args + init.args.kwonlyargs} - {"self"}
                read_in_class = {
                    node.attr
                    for method in cls.body
                    if isinstance(method, ast.FunctionDef) and method.name != "__init__"
                    for node in ast.walk(method)
                    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                }
                for stmt in ast.walk(init):
                    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                        continue
                    target = stmt.targets[0]
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and isinstance(stmt.value, ast.Name)
                            and stmt.value.id in params
                            and target.attr not in read_in_class
                            and target.attr not in read_anywhere):
                        found.append(
                            f"{path.relative_to(_ROOT)}:{stmt.lineno}: "
                            f"{cls.name}.{target.attr}"
                        )
    return found


def test_no_constructor_parameter_is_stored_and_never_read():
    """A signature that asks for something it does not use is a lie.

    Vulture does not see this class of defect -- the attribute is assigned,
    which counts as a use -- so three of them accumulated: a log filename, a
    logger on a class that only draws frames, and a whole view. Each one made
    every call site and every test double hand over a value that went
    nowhere.
    """
    unread = _stored_but_unread_parameters()

    assert not unread, "Stored and never read:\n" + "\n".join(unread)
