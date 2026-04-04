# Genau

## Running tests

Always use the project venv — several dependencies (`pygame-ce`, `opencv-python`) are not installed system-wide and will cause import errors if you use the bare `python` interpreter.

```bash
"C:/path/to/suite-root/projects/genau/.venv/Scripts/python.exe" -m pytest tests/ -v
```

In a worktree, the `.venv` does not exist locally — use the absolute path above (it points to the main repo's venv, which is fine for running tests).
