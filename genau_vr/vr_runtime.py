"""Is the VR runtime ready — and if not, can we bring it up and back down?

GenauVR launches hidden from a shortcut, so a startup that dies on its way to
the headset leaves nothing on screen to read. Asking this question *before*
decoding a clip or opening a window keeps the failure fast and the answer
specific: no runtime at all, a runtime whose headset is off, or ready to render.

It comes up hidden, so quitting it falls to us too: :func:`stop_runtime`.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

# Re-exported: the answer this module reaches for lives in a module with no
# platform in it, so the popup path can be read -- and tested -- without one.
from genau_vr.vr_readiness import APP_NAME, Probe, Readiness, explain  # noqa: F401

# Where the registry and the OpenXR loader are, they are bound here, at the same
# point in this module as before.  Where they are not, the name stays bound — to
# None — so the module still imports, the two flags say plainly that it did not
# get them, and the two functions that need them name which one they wanted
# rather than reading an answer out of nothing.  Without this, one import
# decided whether four of this unit's seven test files existed at all.
_MISSING: dict[str, str] = {}

try:
    import winreg
except ImportError as _exc:
    winreg = None  # type: ignore[assignment]
    _MISSING["winreg"] = str(_exc)

try:
    import xr
except Exception as _exc:  # pyopenxr raises NotImplementedError off Windows, not ImportError
    xr = None  # type: ignore[assignment]
    _MISSING["xr"] = str(_exc)

WINREG_AVAILABLE: bool = winreg is not None
OPENXR_AVAILABLE: bool = xr is not None

logger = logging.getLogger(__name__)


def _require(module: object, name: str) -> None:
    """Refuse, naming what this machine lacks, rather than read a stand-in."""
    if module is None:
        raise RuntimeError(
            f"genau_vr.vr_runtime needs {name}, which did not import here "
            f"({_MISSING.get(name) or 'reason unrecorded'}).  GenauVR runs on Windows."
        )

# A cold VR runtime takes its time: the client starts, brings up its service,
# and only then does the headset answer. Poll rather than guess at a fixed wait.
STARTUP_TIMEOUT_S = 45.0
POLL_S = 1.0

_OPENXR_KEY = r"SOFTWARE\Khronos\OpenXR\1"

# An OpenXR runtime registers itself at <vendor root>/Runtime/<name>.json, while
# the thing a user starts to bring that runtime up lives elsewhere under the same
# root. Only runtimes we can find a launcher for get started for the user;
# anything else is reported so they can start it themselves.
_LAUNCHER_RELATIVE_PATHS = (
    Path("PimaxClient") / "pimaxui" / "PimaxClient.exe",
)

# Putting it back down again.  Pimax publishes no CLI for this: _QUIT_SERVICES
# are the commands its own client logs itself running on Exit, through the tool
# beside the runtime it registered, and PiPlayService's blocks until pi_server
# -- the display server whose exit is the headset going off -- has gone.  A
# renamed service would cost a headset left on, not a broken session.
_QUIT_TOOL_NAME = "launcher.exe"
_QUIT_SERVICES = ("PiPlatformService", "PiPlayService")  # the client's own order
_DISPLAY_SERVER_NAME = "pi_server.exe"
QUIT_TIMEOUT_S = 15.0  # PiPlayService's quit waits on pi_server: ~3s in practice

def probe() -> Probe:
    """Ask OpenXR for a head-mounted display, without opening a window."""
    _require(xr, "xr")
    try:
        instance = xr.create_instance(
            xr.InstanceCreateInfo(
                application_info=xr.ApplicationInfo(APP_NAME, 0, "", 0, xr.Version(1, 0, 0)),
            )
        )
    except xr.exception.RuntimeUnavailableError as exc:
        return Probe(readiness=Readiness.NO_RUNTIME, detail=str(exc))
    except Exception as exc:  # every loader failure has to reach the popup
        return Probe(readiness=Readiness.FAILED, detail=str(exc))

    try:
        xr.get_system(
            instance,
            xr.SystemGetInfo(form_factor=xr.FormFactor.HEAD_MOUNTED_DISPLAY),
        )
    except xr.exception.FormFactorUnavailableError as exc:
        return Probe(readiness=Readiness.NO_HEADSET, detail=str(exc))
    except Exception as exc:  # likewise for anything the runtime itself raises
        return Probe(readiness=Readiness.FAILED, detail=str(exc))
    finally:
        _release_instance(instance)
    return Probe(readiness=Readiness.READY)


def _release_instance(instance: object) -> None:
    """Hand the probe's instance back, without that becoming the answer.

    By the time this runs ``probe()`` has decided what to report, and a runtime
    shutting down under it must not turn that into an exception leaving
    ``probe()`` -- past ``ensure_ready()``'s polling loop, and past the popup
    every loader failure has to reach.  The leak this trades for is a probe's
    worth of one process that is on its way to a dialog either way.
    """
    try:
        xr.destroy_instance(instance)
    except Exception:
        logger.warning("Could not release the probe's OpenXR instance", exc_info=True)


def active_runtime_json() -> Path | None:
    """Where Windows says the current OpenXR runtime is registered."""
    _require(winreg, "winreg")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _OPENXR_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "ActiveRuntime")
    except OSError:
        return None
    return Path(value)


def launcher_for_runtime(runtime_json: Path) -> Path | None:
    """The executable that brings up the runtime registered at *runtime_json*."""
    vendor_root = runtime_json.parent.parent
    for relative in _LAUNCHER_RELATIVE_PATHS:
        candidate = vendor_root / relative
        if candidate.is_file():
            return candidate
    return None


def runtime_launcher() -> Path | None:
    """The executable that brings up whichever OpenXR runtime is active."""
    runtime_json = active_runtime_json()
    if runtime_json is None:
        return None
    return launcher_for_runtime(runtime_json)


def process_running(image_name: str) -> bool:
    """Whether any process with this image name is running."""
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH", "/FO", "CSV"],
            text=True,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return image_name.lower() in output.lower()


def start_runtime(launcher: Path) -> None:
    """Start the VR runtime's own client, the way its desktop shortcut would."""
    logger.info("Starting VR runtime: %s", launcher)
    subprocess.Popen([str(launcher)], cwd=str(launcher.parent), **hidden_subprocess_kwargs())


def runtime_was_running() -> bool:
    """Whether the VR runtime was already up before this session asked for it."""
    return process_running(_DISPLAY_SERVER_NAME)


def runtime_quit_tool() -> Path | None:
    """The vendor tool that quits whichever OpenXR runtime is active."""
    runtime_json = active_runtime_json()
    if runtime_json is None:
        return None
    candidate = runtime_json.parent / _QUIT_TOOL_NAME
    return candidate if candidate.is_file() else None


def stop_runtime() -> None:
    """Quit the runtime the way its own client does -- for one WE started only."""
    if not WINREG_AVAILABLE:
        return
    launcher = runtime_launcher()
    if launcher is not None and process_running(launcher.name):
        logger.info("Stopping VR runtime client: %s", launcher.name)
        _run_quietly(["taskkill", "/IM", launcher.name, "/T", "/F"])  # first: it restarts them
    tool = runtime_quit_tool()
    if tool is None:
        logger.info("No VR runtime quit tool to run")
        return
    for service in _QUIT_SERVICES:
        logger.info("Quitting VR runtime service: %s", service)
        _run_quietly([str(tool), service, "quit"], cwd=tool.parent)


def _run_quietly(command: list[str], *, cwd: Path | None = None) -> None:
    """Run *command* for its effect: this is teardown, so log, never raise."""
    try:
        subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=QUIT_TIMEOUT_S,
            cwd=None if cwd is None else str(cwd),
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("Could not run %s", command[0], exc_info=True)


def ensure_ready(*, timeout_s: float = STARTUP_TIMEOUT_S, poll_s: float = POLL_S) -> Probe:
    """Get VR to a state GenauVR can render into, starting the runtime if needed.

    A runtime that is already up and still has no headset for us is reported
    straight back: restarting its client cannot power on a headset, and waiting
    out the timeout would only delay saying so.
    """
    result = probe()
    if result.readiness is Readiness.READY:
        return result

    launcher = runtime_launcher()
    if launcher is None:
        logger.info("No VR runtime launcher to start (%s)", result.readiness.value)
        return result
    if process_running(launcher.name):
        logger.info("VR runtime already running, but %s", result.readiness.value)
        return result

    start_runtime(launcher)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        result = probe()
        if result.readiness is Readiness.READY:
            logger.info("VR runtime came up")
            return result
    logger.warning(
        "VR runtime did not come up within %.0fs (%s)", timeout_s, result.readiness.value
    )
    return result
