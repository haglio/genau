"""What GenauVR does on a machine with no OpenXR loader.

``genau_vr`` is a VR app, but most of what its suite checks is not about VR:
the error popups, the crash log, the volume curve, the clip scan. All of it was
gated behind ``import xr`` at the top of ``vr_runtime``, so on a machine without
the loader those files were not failing tests — they were four collection
errors, and every test in them was silently dropped from the run.

These cases pin the other outcome: the modules import, and the two calls that
genuinely need the platform refuse by name rather than reading an answer out of
nothing. The child interpreter below refuses to load ``xr`` at all, so the
import half asks the same question on Windows, where the loader is always there,
as it does on a machine where it never is; the refusal half forces the binding
down and asks it directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from genau_vr import vr_runtime, vr_session

REPO_DIR = Path(__file__).resolve().parent.parent

_REFUSE_TO_IMPORT = '''
import sys

class _Absent:
    """An import hook that says a module is not here, wherever here is."""

    def __init__(self, names):
        self._names = set(names)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self._names:
            raise ImportError("no module named " + repr(fullname) + " on this machine")
        return None

sys.meta_path.insert(0, _Absent(%r))
'''


def _run_without(names: tuple[str, ...], body: str) -> subprocess.CompletedProcess:
    """Run *body* in a child that cannot import any of *names*.

    ``PYTHONPATH`` is dropped so the child resolves the way a launch does, and
    so it cannot pick up a stand-in module a developer put on the path.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-c", (_REFUSE_TO_IMPORT % (names,)) + body],
        cwd=str(REPO_DIR), env=env, capture_output=True, text=True, timeout=180,
    )


def test_the_readiness_answer_needs_no_platform_at_all():
    """What the user is shown when VR is missing must not need VR to exist.

    Not even the registry: this child refuses ``winreg`` as well, which is
    stdlib on Windows and so cannot be missing there — the point is that this
    module never reaches for it, on any machine.
    """
    result = _run_without(
        ("xr", "winreg"),
        "from genau_vr.vr_readiness import Probe, Readiness, explain\n"
        "assert explain(Probe(Readiness.NO_HEADSET, 'powered off')).startswith('No VR headset')\n",
    )

    assert result.returncode == 0, result.stderr


def test_the_runtime_answers_with_the_platform_free_types():
    """One set of types, so app.py and the popup tests share them."""
    from genau_vr import vr_readiness

    assert vr_runtime.Probe is vr_readiness.Probe
    assert vr_runtime.Readiness is vr_readiness.Readiness
    assert vr_runtime.explain is vr_readiness.explain


def test_the_vr_modules_import_where_there_is_no_openxr():
    result = _run_without(
        ("xr",),
        "import genau_vr.vr_runtime\n"
        "import genau_vr.vr_session\n"
        "import genau_vr.app\n",
    )

    assert result.returncode == 0, result.stderr


def test_the_flags_say_what_the_module_actually_got():
    assert vr_runtime.OPENXR_AVAILABLE is (vr_runtime.xr is not None)
    assert vr_runtime.WINREG_AVAILABLE is (vr_runtime.winreg is not None)


def test_probing_without_the_loader_names_it_instead_of_answering():
    """A Probe read off an absent loader is the worst outcome available.

    It would reach the popup as a plain readiness, and the user would be told
    something about their headset that nothing ever asked their headset.
    """
    with patch.object(vr_runtime, "xr", None), pytest.raises(RuntimeError, match="xr"):
        vr_runtime.probe()


def test_reading_the_registry_without_winreg_names_it():
    with patch.object(vr_runtime, "winreg", None), pytest.raises(RuntimeError, match="winreg"):
        vr_runtime.active_runtime_json()


def test_a_session_without_the_loader_names_it_rather_than_half_starting():
    with patch.object(vr_session, "xr", None), pytest.raises(RuntimeError, match="OpenXR"):
        vr_session.VRSession()
