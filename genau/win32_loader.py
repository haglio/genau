"""Binding the Win32 DLLs, and saying plainly where they cannot be bound.

``genau.win32`` reaches ``ctypes.windll`` while it is being imported: the two
DLL handles are bound once, at module scope, so the call sites stay bare.  That
makes the binding a single point of failure for more than the code that needs
Windows — off Windows ``ctypes`` has no ``windll`` at all, the import raises,
and every test module that names ``genau.win32`` is dropped from the run with
it.  One import then decides whether a file's tests exist.

So the binding asks first.  ``WIN32_AVAILABLE`` says whether this interpreter's
``ctypes`` carries the Windows half — true on Windows, and true in a test
process that has faked that surface in.  Where it does not, ``load_dll`` hands
back a stand-in that raises :class:`Win32Unavailable`, naming the entry point,
the moment anything calls it.  Nothing degrades quietly: a call that should
never have been reached says so rather than returning a plausible zero, which
for this module would be an HRESULT of 0 — success.
"""
from __future__ import annotations

import ctypes
from typing import Any

WIN32_AVAILABLE = hasattr(ctypes, "windll")


class Win32Unavailable(RuntimeError):
    """A Win32 entry point was called in a process that could not bind it."""


class _UnavailableEntryPoint:
    """One exported function, on a machine that has no such export."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        raise Win32Unavailable(f"{self._name} needs a Windows ctypes; this process has none")


class _UnavailableDll:
    """One DLL, on a machine that has no such DLL.

    Each entry point is made once and kept, so a test that patches one finds
    the same object the code will call.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, entry_point: str) -> _UnavailableEntryPoint:
        if entry_point.startswith("__"):
            raise AttributeError(entry_point)
        stand_in = _UnavailableEntryPoint(f"{self._name}.{entry_point}")
        setattr(self, entry_point, stand_in)
        return stand_in


def load_dll(name: str) -> Any:
    """The handle for the *name* DLL, or a stand-in that refuses to be called."""
    if not WIN32_AVAILABLE:
        return _UnavailableDll(name)
    return getattr(ctypes.windll, name)  # type: ignore[attr-defined]
