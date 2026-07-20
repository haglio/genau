"""A name referenced but never bound — the crash that waits for its branch to run.

Nau's event loop called a helper on every mouse move.  The helper was never
written, and nothing found out until a cursor crossed the player's window mid
session and took it down.  A long-running loop is mostly branches the suite never
executes, so no amount of unit testing reaches them all — but the compiler
already resolves every name while compiling, and a name it can only resolve to
module scope, that module scope never binds, is a `NameError` with a date on it.

This is the counterpart to `test_dead_code`: that one finds what is defined and
never used, this one finds what is used and never defined.
"""
from __future__ import annotations

import builtins
import symtable
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGES = ("genau", "genau_vr", "nau", "sanitize", "tests")

# What every module has without binding it.  `__conditional_annotations__` is the
# compiler's own: 3.14 builds annotations lazily and stashes the conditionally
# defined ones under that name, in the modules that have any.
_GIVEN = set(dir(builtins)) | {
    "__annotations__", "__builtins__", "__conditional_annotations__", "__debug__",
    "__doc__", "__file__", "__loader__", "__name__", "__package__", "__path__",
    "__spec__",
}


def _bound_at_module_scope(module: symtable.SymbolTable) -> set[str]:
    return {sym.get_name() for sym in module.get_symbols()
            if sym.is_assigned() or sym.is_imported() or sym.is_namespace()}


def _collect(table: symtable.SymbolTable, bound: set[str], where: Path,
             found: list[str]) -> None:
    for sym in table.get_symbols():
        name = sym.get_name()
        # Resolved to module scope (not a local, not a closure, not an import)
        # and read — but nothing up there ever puts it in place.
        if sym.is_global() and sym.is_referenced() and name not in bound:
            found.append(f"{where}:{table.get_lineno()} in {table.get_name()}(): {name}")
    for child in table.get_children():
        _collect(child, bound, where, found)


def _undefined_names(path: Path) -> list[str]:
    module = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    found: list[str] = []
    _collect(module, _bound_at_module_scope(module) | _GIVEN, path.relative_to(_ROOT), found)
    return found


def test_every_name_referenced_is_one_that_exists():
    found = [finding
             for package in _PACKAGES
             for py in sorted((_ROOT / package).rglob("*.py"))
             if "__pycache__" not in py.parts
             for finding in _undefined_names(py)]

    assert not found, "Referenced but never defined:\n" + "\n".join(found)
