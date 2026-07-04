"""Locate the bundled libmpv DLL so ``import mpv`` can find it.

python-mpv resolves libmpv through the Windows DLL search path (``%PATH%``),
not ``os.add_dll_directory``, so the vendored ``vendor/libmpv-2.dll`` must be
on PATH before ``import mpv``.  The DLL is ~117 MB and is NOT committed — it
is fetched locally (see the README) into ``genau/vendor/``.
"""
from __future__ import annotations

import os
from pathlib import Path


def libmpv_dir() -> Path:
    """The repo's ``vendor/`` directory that holds ``libmpv-2.dll``."""
    return Path(__file__).resolve().parent.parent / "vendor"


def add_libmpv_to_path() -> None:
    """Prepend the vendor dir to ``%PATH%`` (once) so ``import mpv`` resolves."""
    vendor = str(libmpv_dir())
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if parts and parts[0] == vendor:
        return
    os.environ["PATH"] = os.pathsep.join([vendor, *[p for p in parts if p != vendor]])
