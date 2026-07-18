# Genau

## Running tests

Always use the project venv — several dependencies (`pygame-ce`, `opencv-python`) are not installed system-wide and will cause import errors if you use the bare `python` interpreter.

```bash
"C:/path/to/suite-root/projects/genau/.venv/Scripts/python.exe" -m pytest tests/ -v
```

In a worktree, the `.venv` does not exist locally — use the absolute path above (it points to the main repo's venv, which is fine for running tests).

## The shared player core

Nau's playback engine, the playlist format and the orchestrator's command/paused
file channel live in `../player_core`, installed editable into this venv —
Fun Time's own players use them too, and none of these apps may reach into
another's repo. A change to any of those belongs there, not here.

**Install it with `--config-settings editable_mode=compat`**, and this repo the
same way:

```bash
"…/genau/.venv/Scripts/python.exe" -m pip install -e ../player_core --config-settings editable_mode=compat
"…/genau/.venv/Scripts/python.exe" -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools' default editable install resolves submodules through a
meta-path finder pointed at the **main checkout**, so a worktree's own `nau/`
and `genau/` are half-shadowed: a module you deleted or edited there keeps
resolving to the main tree, and the suite goes green on code you are not
running. `player_core`'s `tests/test_install.py` catches its half of this.
