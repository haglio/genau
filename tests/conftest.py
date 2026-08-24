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
      entry for the checkout, and that tree's ``nau``/``genau`` win.  Loud when
      the trees have drifted enough to break an import; silent when they have
      not, which is worse: a green suite proving nothing about the code you have.

    Both are beaten by putting this tree first, and *moving* it there rather
    than inserting only when absent — the editable install already lists the
    real checkout further down, which is precisely why the old
    ``if not in sys.path`` guard never fired for the second case.
    """
    while _PROJECT_ROOT in sys.path:
        sys.path.remove(_PROJECT_ROOT)
    sys.path.insert(0, _PROJECT_ROOT)
    for name in ("nau", "genau"):
        module = importlib.import_module(name)
        home = Path(module.__file__).resolve().parent.parent
        if home != Path(_PROJECT_ROOT):
            raise RuntimeError(
                f"tests in {_PROJECT_ROOT} imported {name} from {home}. "
                "Two trees of this repo are on sys.path and the wrong one won; "
                "the suite would be testing code you are not running."
            )


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


@pytest.fixture()
def tmp_path() -> Path:
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


@pytest.fixture()
def mock_pygame(monkeypatch):
    """Stand in for the pygame names ``genau.pygame_view`` binds, and return the
    fake ``pygame`` module itself.

    Patch the *view*, not ``sys.modules``.  The view does its imports at module
    scope -- ``import pygame`` and ``from pygame._sdl2.video import Renderer,
    Texture, Window`` -- so swapping the entries in ``sys.modules`` reaches those
    names only while the view has never been imported.  Once anything has
    imported it (``nau.app`` does), the bindings are already the real SDL ones
    and the swap is inert: the tests behind this fixture then build real windows
    on the machine that also runs the live players.  Patching the attributes the
    view holds asks nothing about what has been imported, or when.
    """
    import genau.pygame_view as pygame_view

    pygame = MagicMock()
    monkeypatch.setattr(pygame_view, "pygame", pygame)
    for name in ("Window", "Renderer", "Texture"):
        monkeypatch.setattr(pygame_view, name, MagicMock())
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
            "render_batch": 6,
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


@pytest.fixture()
def cfg_path(tmp_path: Path) -> Path:
    """Return path to a written minimal valid genau config file."""
    return _write_genau_config(tmp_path)


@pytest.fixture()
def cfg_factory(tmp_path: Path):
    """Return a factory that writes a config with optional overrides."""
    def factory(overrides: dict | None = None) -> Path:
        return _write_genau_config(tmp_path, overrides)
    return factory
