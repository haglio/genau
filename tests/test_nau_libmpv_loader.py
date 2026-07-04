from __future__ import annotations

from pathlib import Path

from nau.libmpv_loader import libmpv_dir, add_libmpv_to_path


def test_libmpv_dir_is_vendor_beside_the_nau_package():
    import nau
    d = libmpv_dir()
    assert d.name == "vendor"
    # vendor/ is a sibling of the nau/ package directory (repo root)
    assert d.parent == Path(nau.__file__).resolve().parent.parent


def test_add_libmpv_to_path_prepends_vendor(monkeypatch):
    monkeypatch.setenv("PATH", "C:\existing")
    add_libmpv_to_path()
    import os
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == str(libmpv_dir())
    assert "C:\existing" in parts


def test_add_libmpv_to_path_is_idempotent(monkeypatch):
    monkeypatch.setenv("PATH", "C:\existing")
    add_libmpv_to_path()
    add_libmpv_to_path()
    import os
    assert os.environ["PATH"].split(os.pathsep).count(str(libmpv_dir())) == 1
