"""Shared pytest fixtures for Genau tests."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _pin_this_tree() -> None:
    """Make this suite import the tree it lives in, whatever the cwd.

    Two different shadows want the front of ``sys.path``:

    * Run from an ancestor directory (``C:/.../projects``), Python can read the
      repo folder ``genau/`` as a namespace package and never reach the real
      one, so ``genau.state`` and friends stop importing.
    * Run from a *sibling tree* — every agent works in a
      ``.claude/worktrees/<name>/`` copy, so several trees with these package
      names coexist — the cwd goes on the path ahead of the editable install's
      entry for the checkout, and that tree's ``genau`` wins.  Loud when
      the trees have drifted enough to break an import; silent when they have
      not, which is worse: a green suite proving nothing about the code you have.

    Both are beaten by putting this tree first, and *moving* it there rather
    than inserting only when absent — the editable install already lists the
    real checkout further down, which is precisely why the old
    ``if not in sys.path`` guard never fired for the second case.

    Neither is beaten by ``sys.path`` alone.  Setuptools' default editable
    install answers from ``sys.meta_path``, which is consulted before any path,
    and its finder handles *immediate children* as well as the top-level name —
    so ``genau`` can resolve here while ``genau.window`` resolves in the main
    checkout, which is the silent half: a module deleted or renamed here goes on
    importing from there and the suite passes over code that is not in this
    tree.  ``--config-settings editable_mode=compat`` writes a plain path entry
    instead of that finder, which this repo's CLAUDE.md asks for; the finder is
    dropped here too, so a venv installed the other way cannot quietly hand this
    suite the wrong tree.
    """
    while _PROJECT_ROOT in sys.path:
        sys.path.remove(_PROJECT_ROOT)
    sys.path.insert(0, _PROJECT_ROOT)
    _drop_editable_finders_for("genau")
    module = importlib.import_module("genau")
    home = Path(module.__file__).resolve().parent.parent
    if home != Path(_PROJECT_ROOT):
        raise RuntimeError(
            f"tests in {_PROJECT_ROOT} imported genau from {home}. "
            "Two trees of this repo are on sys.path and the wrong one won; "
            "the suite would be testing code you are not running."
        )


def _drop_editable_finders_for(*packages: str) -> None:
    """Take setuptools' editable finder off ``sys.meta_path`` for *packages*.

    The finder is installed as a class, and the map of package to checkout is a
    global in the module that defines it — so which packages a finder owns is
    read from that module rather than from the entry itself.
    """
    def owns_one(finder) -> bool:
        home = sys.modules.get(getattr(finder, "__module__", ""))
        mapping = getattr(home, "MAPPING", {})
        return any(package in mapping for package in packages)

    sys.meta_path[:] = [f for f in sys.meta_path if not owns_one(f)]


_pin_this_tree()

# Drive SDL headless for the whole suite. Agents run these tests on every commit,
# on the machine that also runs the live players; anything that builds a view
# without the mock -- a fixture that stops reaching it, a new test that skips it
# -- would otherwise throw a real window onto that screen. The merge gate sets
# this in its own env, which does nothing for a run started by hand. setdefault
# lets a developer override it to watch something on a real display.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


TMP_ROOT = Path(
    os.environ.get(
        "GENAU_PYTEST_TMP_ROOT",
        str(Path(__file__).resolve().parent.parent / ".tmp-pytest-local"),
    )
).resolve()


@pytest.fixture
def tmp_path() -> Path:
    """pytest's own, rooted in this repo rather than under the system temp dir.

    Shadowing the builtin has costs worth knowing before anyone leans on the
    builtin's behaviour: `--basetemp` does nothing, and pytest's
    keep-the-last-three-runs retention is gone, so a failed test's files are
    removed before anyone can look at them.  `GENAU_PYTEST_TMP_ROOT` is how a
    run puts the root somewhere else; `.tmp-pytest-local/` and `.coverage` are
    both in `.gitignore`, so a run killed part-way cannot leave the untracked
    file that would stop the next merge.
    """
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = (TMP_ROOT / f"case_{uuid.uuid4().hex}").resolve()
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def _cleanup_tmp_root():
    """Remove TMP_ROOT after the session if it exists and is empty."""
    yield
    try:
        if TMP_ROOT.is_dir() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()
    except OSError:
        pass


@pytest.fixture
def mock_pygame(monkeypatch):
    """Stand in for the pygame names ``genau.window`` and ``genau.pygame_view``
    bind, and return the fake ``pygame`` module itself.

    Patch the *modules*, not ``sys.modules``.  Both do their imports at module
    scope -- ``import pygame`` and ``from pygame._sdl2.video import ...`` -- so
    swapping the entries in ``sys.modules`` reaches those names only while
    neither has ever been imported.  Once anything has imported them
    (``genau.app`` does), the bindings are already the real SDL ones and the swap
    is inert: the tests relying on this fixture then build real windows on the
    machine that also runs the live players.  Patching the attributes each
    module holds asks nothing about what has been imported, or when.

    Both modules, because the window and the scene drawn in it are two: the
    window binds ``Window`` and ``Renderer``, the scene binds ``Texture``, and
    each holds its own ``pygame``.
    """
    from genau import pygame_view, window

    pygame = MagicMock()
    for module in (pygame_view, window):
        monkeypatch.setattr(module, "pygame", pygame)
        for name in ("Window", "Renderer", "Texture"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, MagicMock())
    return pygame


def _write_genau_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    """Write a minimal valid genau config JSON to tmp_path and return the path."""
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "clips").mkdir(exist_ok=True)

    cfg: dict = {
        "clips_dir": str(tmp_path / "clips"),
        "state_dir": str(tmp_path / "state"),
        "genau": {
            "shuffle_on_load": True,
            "beats_per_loop": 1.0,
            "clip_cache_size": 2,
            "bpm_smoothing": 0.14,
            "sync_strength": 0.35,
            "udp_host": "127.0.0.1",
            "udp_port": 50555,
            "notify_host": "127.0.0.1",
            "notify_port": 50556,
            "resize_debounce_ms": 120,
            "tcode_udp_host": "127.0.0.1",
            "tcode_udp_port": 50557,
        },
    }

    if overrides:
        _deep_merge(cfg, overrides)

    config_path = tmp_path / "genau_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    return config_path


def _deep_merge(base: dict, override: dict) -> None:
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """Return path to a written minimal valid genau config file."""
    return _write_genau_config(tmp_path)


@pytest.fixture
def cfg_factory(tmp_path: Path):
    """Return a factory that writes a config with optional overrides."""
    def factory(overrides: dict | None = None) -> Path:
        return _write_genau_config(tmp_path, overrides)
    return factory
