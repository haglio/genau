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
        str(_ROOT / "genau_vr"),
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
# in one module hides behind a real one in its neighbor.
_DEAD_CODE_LINT_RULES = "F401,F811,F841"

# ARG names the same class one level out: a parameter the body never reads.
# Over the packages only -- the suite's fakes stand in for protocols and are
# full of arguments they are right not to use -- and without ARG005, whose
# every hit here is a `lambda _x: None` default callback doing its job.
_DEAD_ARG_LINT_RULES = "ARG001,ARG002,ARG003,ARG004"


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


def test_no_function_takes_an_argument_it_never_reads():
    """A signature that asks for something it does not use is a lie -- the same
    defect the constructor scan below catches, one level out.

    genau_vr's `apply_runtime_command` kept an `engine` after its last reader,
    the OFFSET_QUARTER_CYCLE branch, turned out to be unreachable.
    """
    cmd = [
        sys.executable, "-m", "ruff", "check",
        "--select", _DEAD_ARG_LINT_RULES,
        "--output-format", "concise",
        *(str(d) for d in PACKAGE_DIRS),
    ]
    result = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)

    assert result.returncode == 0, (
        f"ruff found unread arguments:\n{result.stdout.strip()}\n{result.stderr.strip()}"
    )


def _tracked_python_files() -> list[Path]:
    """Every .py in the repo. Parts are taken relative to the root because
    this repo is worked in a git worktree *under* .claude/, so an
    absolute-path exclusion would quietly skip the whole tree."""
    return [
        path for path in _ROOT.rglob("*.py")
        if not any(part in {".venv", "__pycache__", ".claude"}
                   for part in path.relative_to(_ROOT).parts)
    ]


def _attribute_names_read_anywhere() -> set[str]:
    """Every ``x.<name>`` read in the tree, plus every string literal.

    The string literals are there so a ``getattr(obj, "thing")`` or a name
    looked up out of a dict counts as a read; the point of this scan is to
    be sure before deleting, not to find every last one.
    """
    names: set[str] = set()
    for path in _tracked_python_files():
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


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _names_read_per_file() -> dict[str, set[str]]:
    """Per file, every plain name and attribute read in it, plus its strings.

    A name is counted as read in the file that defines it only if it is used
    there beyond the assignment itself, which is what lets the caller ask
    "and nowhere else either".
    """
    per_file: dict[str, set[str]] = {}
    for path in _tracked_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[0])
        per_file[str(path.relative_to(_ROOT))] = names
    return per_file


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


def _unread_module_constants() -> list[str]:
    """Module-level names assigned in a package and read nowhere in the tree.

    Vulture does not report unused module-level constants at all, so this is
    the third blind spot: a `_THUMB_H = 64` nothing measures sits there for
    good. A name is only reported when it appears in no other file either, so
    a constant one module defines and another imports is safe.
    """
    read = _names_read_per_file()
    found: list[str] = []
    for package in PACKAGE_DIRS:
        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            here = str(path.relative_to(_ROOT))
            elsewhere = set().union(
                *(names for name, names in read.items() if name != here))
            for node in tree.body:
                targets = []
                if isinstance(node, ast.Assign):
                    targets = [t for t in node.targets if isinstance(t, ast.Name)]
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    targets = [node.target]
                for target in targets:
                    if target.id not in read[here] and target.id not in elsewhere:
                        found.append(f"{here}:{node.lineno}: {target.id}")
    return found


def test_no_module_level_constant_goes_unread():
    """A constant nobody measures against is a number with no meaning left."""
    unread = _unread_module_constants()

    assert not unread, "Assigned and never read:\n" + "\n".join(unread)


def _is_collected_by_pytest(node: ast.FunctionDef) -> bool:
    """A fixture or a hook is called by pytest, not by a name in the file."""
    if node.name.startswith(("test", "pytest_")):
        return True
    return any("fixture" in ast.unparse(d) or "hookimpl" in ast.unparse(d)
               for d in node.decorator_list)


def _uncalled_test_helpers() -> list[str]:
    """Helpers in tests/ that their own file never calls and no file imports."""
    imported = {
        alias.name
        for path in _tracked_python_files()
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    found: list[str] = []
    for path in sorted((_ROOT / "tests").rglob("*.py")):
        tree = _parse(path)
        used = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load))
            or (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load))
        }
        for node in tree.body:
            if (isinstance(node, ast.FunctionDef)
                    and not _is_collected_by_pytest(node)
                    and node.name not in used
                    and node.name not in imported):
                found.append(f"{path.relative_to(_ROOT)}:{node.lineno}: {node.name}")
    return found


def test_no_test_helper_is_written_and_never_called():
    """The suite is not checked by the gates that check the packages.

    vulture is pointed at genau/, nau/ and genau_vr/ only -- pointing it at
    tests/ as well would report every fake-collaborator method as unused --
    so a leftover helper in a test file accumulates unseen.
    """
    uncalled = _uncalled_test_helpers()

    assert not uncalled, "Written and never called:\n" + "\n".join(uncalled)


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
