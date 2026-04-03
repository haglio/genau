"""Minimal Win32 helpers for Genau taskbar identity."""
from __future__ import annotations

import ctypes

_shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]

APP_USER_MODEL_ID = "Genau.App"


def set_app_user_model_id(app_id: str) -> None:
    """Set the AppUserModelID for the current process.

    Must be called before any windows are created so the taskbar groups
    the process's windows under the correct pinned shortcut / icon.
    """
    hr = _shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    if hr < 0:
        raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: HRESULT 0x{hr:08x}")
