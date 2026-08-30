"""Win32 helpers for Genau taskbar identity and shortcut AUMID stamping."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import uuid
from pathlib import Path

from genau.win32_loader import load_dll

_shell32 = load_dll("shell32")
_ole32 = load_dll("ole32")
_user32 = load_dll("user32")
_kernel32 = load_dll("kernel32")

APP_USER_MODEL_ID = "Genau.App"

logger = logging.getLogger(__name__)

# Win32 window styles, for the transparency below.
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x80000
_LWA_COLORKEY = 0x1


def _colorref(rgb: tuple[int, int, int]) -> int:
    """A Win32 COLORREF, which is 0x00BBGGRR — the reverse of RGB.

    Written the wrong way round the key matches a color nothing paints, so
    every pixel stays opaque and the HUD hides the player underneath it.
    """
    red, green, blue = rgb
    return red | (green << 8) | (blue << 16)


class LayeredWindow:
    """Color-key transparency on one window, whose handle is taken once.

    The handle is found by the window's caption at construction, while the
    caption is still the one the window was created with.  Looking it up again
    on every toggle is what tied the transparency to the title: the title
    changes when the HUD comes up, so the lookup had to happen after the rename
    and before the toggle -- an ordering held together by a comment, in a window
    fun_time separately finds by caption substring.

    A handle that cannot be found is said once and then let be: the transparency
    is what lets Nau's video show through Genau's overlay, so losing it costs
    the Hybrid look rather than the session.
    """

    def __init__(self, title: str, color_key: tuple[int, int, int], *, user32=None):
        self._user32 = user32 if user32 is not None else _user32
        self._color_key = color_key
        self.hwnd = self._user32.FindWindowW(None, title)
        if not self.hwnd:
            logger.warning("HUD: no window found with the caption %r", title)

    def set_transparent(self, transparent: bool) -> None:
        if not self.hwnd:
            return
        style = self._user32.GetWindowLongW(self.hwnd, _GWL_EXSTYLE)
        if not transparent:
            self._user32.SetWindowLongW(
                self.hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED)
            logger.info("HUD: layered window disabled")
            return
        self._user32.SetWindowLongW(
            self.hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
        key = _colorref(self._color_key)
        if self._user32.SetLayeredWindowAttributes(self.hwnd, key, 0, _LWA_COLORKEY):
            logger.info("HUD: layered window enabled (hwnd=%#x, colorkey=%#08x)",
                        self.hwnd, key)
        else:
            logger.warning("HUD: SetLayeredWindowAttributes failed (error %d)",
                           _kernel32.GetLastError())


def set_app_user_model_id(app_id: str) -> None:
    """Set the AppUserModelID for the current process.

    Must be called before any windows are created so the taskbar groups
    the process's windows under the correct pinned shortcut / icon.
    """
    hr = _shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    if hr < 0:
        raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: HRESULT 0x{hr:08x}")


# --- COM helpers for shortcut AUMID stamping ---

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_ALL = 0x17


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(s: str) -> GUID:
    u = uuid.UUID(s)
    return GUID(u.time_low, u.time_mid, u.time_hi_version,
                (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


PKEY_AppUserModel_ID = PROPERTYKEY(
    _make_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5
)

VT_LPWSTR = 31


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.wintypes.LPWSTR),
        ("_pad", ctypes.c_void_p),
    ]


CLSID_ShellLink = _make_guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = _make_guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = _make_guid("0000010B-0000-0000-C000-000000000046")
IID_IPropertyStore = _make_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")

STGM_READWRITE = 0x00000002
_VTBL_QI = 0
_VTBL_RELEASE = 2
_VTBL_IPF_LOAD = 5
_VTBL_IPF_SAVE = 6
_VTBL_IPS_SET_VALUE = 6
_VTBL_IPS_COMMIT = 7


def _vtbl_call(obj_addr: int, index: int, restype: type, *argtypes: type):
    vtbl = ctypes.c_void_p.from_address(obj_addr).value
    func_ptr = ctypes.c_void_p.from_address(
        vtbl + index * ctypes.sizeof(ctypes.c_void_p)
    ).value
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(func_ptr)


def _release(obj_addr: int) -> None:
    _vtbl_call(obj_addr, _VTBL_RELEASE, ctypes.c_ulong)(obj_addr)


def _query_interface(obj_addr: int, iid: GUID) -> int:
    out = ctypes.c_void_p()
    hr = _vtbl_call(obj_addr, _VTBL_QI, ctypes.HRESULT,
                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
        obj_addr, ctypes.byref(iid), ctypes.byref(out))
    if hr < 0:
        raise OSError(f"QueryInterface failed: HRESULT 0x{hr:08x}")
    return out.value


def set_shortcut_app_user_model_id(lnk_path: str, app_id: str) -> None:
    """Set the AppUserModelID property on a .lnk shortcut file."""
    _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        _set_lnk_aumid(lnk_path, app_id)
    finally:
        _ole32.CoUninitialize()


def _set_lnk_aumid(lnk_path: str, app_id: str) -> None:
    shell_link = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(
        ctypes.byref(CLSID_ShellLink), None, CLSCTX_ALL,
        ctypes.byref(IID_IShellLinkW), ctypes.byref(shell_link),
    )
    if hr < 0:
        raise OSError(f"CoCreateInstance(ShellLink) failed: HRESULT 0x{hr:08x}")
    try:
        persist_file = _query_interface(shell_link.value, IID_IPersistFile)
        try:
            hr = _vtbl_call(persist_file, _VTBL_IPF_LOAD,
                            ctypes.HRESULT, ctypes.wintypes.LPCWSTR, ctypes.c_ulong)(
                persist_file, lnk_path, STGM_READWRITE)
            if hr < 0:
                raise OSError(f"IPersistFile::Load failed: HRESULT 0x{hr:08x}")

            prop_store = _query_interface(shell_link.value, IID_IPropertyStore)
            try:
                pv = PROPVARIANT()
                pv.vt = VT_LPWSTR
                pv.pwszVal = app_id

                hr = _vtbl_call(prop_store, _VTBL_IPS_SET_VALUE,
                                ctypes.HRESULT,
                                ctypes.POINTER(PROPERTYKEY),
                                ctypes.POINTER(PROPVARIANT))(
                    prop_store,
                    ctypes.byref(PKEY_AppUserModel_ID),
                    ctypes.byref(pv))
                if hr < 0:
                    raise OSError(f"IPropertyStore::SetValue failed: HRESULT 0x{hr:08x}")

                hr = _vtbl_call(prop_store, _VTBL_IPS_COMMIT, ctypes.HRESULT)(prop_store)
                if hr < 0:
                    raise OSError(f"IPropertyStore::Commit failed: HRESULT 0x{hr:08x}")
            finally:
                _release(prop_store)

            hr = _vtbl_call(persist_file, _VTBL_IPF_SAVE,
                            ctypes.HRESULT, ctypes.wintypes.LPCWSTR, ctypes.wintypes.BOOL)(
                persist_file, lnk_path, True)
            if hr < 0:
                raise OSError(f"IPersistFile::Save failed: HRESULT 0x{hr:08x}")
        finally:
            _release(persist_file)
    finally:
        _release(shell_link.value)


def stamp_pinned_shortcuts(app_id: str, *, include: str, exclude: str | None = None) -> None:
    """Stamp pinned taskbar shortcuts matching *include* with *app_id*.

    Shortcuts whose stem (lowered) contains *exclude* are skipped, preventing
    e.g. a "genau" pattern from also stamping "genauvr" shortcuts.
    """
    _log = logging.getLogger(__name__)
    appdata = os.environ.get("APPDATA", "")
    pin_dir = Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
    if not pin_dir.is_dir():
        return
    for lnk in pin_dir.glob("*.lnk"):
        stem = lnk.stem.lower()
        if include not in stem:
            continue
        if exclude and exclude in stem:
            continue
        try:
            set_shortcut_app_user_model_id(str(lnk), app_id)
            _log.info("Stamped AppUserModelID on %s", lnk)
        except OSError as exc:
            _log.warning("Could not stamp AppUserModelID on %s: %s", lnk, exc)


def take_taskbar_identity(
    app_id: str, *, include: str, exclude: str | None = None, config_path: str | Path,
) -> None:
    """Claim this process's place on the taskbar, and stamp the pin if it is ours.

    The two halves look alike and are not.  Setting the process AUMID touches
    nothing outside this process — it is only how the taskbar groups our windows
    under the right icon, so it runs for every session however it was started.

    Stamping edits a shortcut under %APPDATA%, outside every checkout, and that
    shortcut launches the installed app.  A session on an explicit --config (a
    test run's temp one, an alternate of the developer's) is a different
    instance, and the pin points at neither of them.

    Paths resolve before comparing: Nau and GenauVR each build their own spelling
    of the one config file, and an argparse default arrives unresolved, so the
    same file must not read as a different app.
    """
    from .config import DEFAULT_CONFIG_PATH

    try:
        set_app_user_model_id(app_id)
    except OSError:
        pass  # Cosmetic: costs the icon, never worth failing to start over.
    if Path(config_path).resolve() != DEFAULT_CONFIG_PATH:
        return
    stamp_pinned_shortcuts(app_id, include=include, exclude=exclude)
