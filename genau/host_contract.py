"""What a host must know to start this app and find its window, published for it.

Fun Time runs this app as one of its session's windows: it names the config,
the folder of clips, the rect, the icon and the taskbar button to join, the six
files the two trade through, and both captions the window wears.  It cannot
import this package -- no app here reaches into another's repo -- so all of
that was spelled on its own side too, from reading this one's source.

Nothing compared the two.  An unknown flag argparse already refuses at the
launch, loudly; the other half of the same drift is a host that STOPS sending
one, and that fell through to a default -- a status file published where the
host was not reading it, a paused flag nobody ever set -- with both suites
green (audit cross/boundaries/cross/003, the fun_time-genau cycle).

Declared once here, used below to BUILD the parser and to refuse a host launch
short of a flag :func:`required_flags` names, and published as
:data:`CONTRACT_FILE` at the checkout root for a host that cannot import this.
Run ``python -m genau.host_contract`` to rewrite it; the suite fails on a copy
that no longer matches.

Standard library only, and nothing of pygame's: a host reads this document with
its own interpreter, and this module is imported to write it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_core.clip_folder import (
    cache_dir_for_clips_folder,
    weird_dir_for_clips_folder,
)

#: The module a host runs.
MODULE = "genau"

#: The tell that a launch is a host's rather than the desktop shortcut's: a
#: window grouped under another app's taskbar button IS one of that app's
#: windows, and only a host asks for that.  There is no mode to switch into
#: here -- this app does the same thing either way -- so this flag does the job
#: Origenerator's ``--fun-time`` does for it.
HOSTED_FLAG = "--taskbar-identity"

#: The config this app loads, and the folder of clips it plays.
CONFIG_FLAG = "--config"
CLIPS_FOLDER_FLAG = "--clips-folder"

#: The rect the host sizes this window to.
RECT_FIELDS = ("x", "y", "width", "height")

#: The files the session and this app trade through: the first three are the
#: host writing to this app (its verbs, its pause, the console panel it draws
#: here), the next two this app publishing back (the drive readout the main
#: player draws in video mode, what the hand is doing), and the last is where a
#: press on that console posts the host's command.  Every one is NAMED by the
#: host: this app resolving them from its own config wrote them into this repo,
#: where the host was never looking.
SESSION_FILES = ("command-file", "paused-file", "console-file",
                 "drive-file", "status-file", "dashboard-cmd-file")

#: The window icon a host hands over, so an Alt-Tab entry says whose window
#: this is.
ICON_FLAG = "--icon"

#: The clip the last session was left showing.  Not required: a session with
#: none to come back to sends nothing and this app opens at the top of the
#: folder.  On the command line rather than the command channel because that
#: channel upper-cases every line, which no path survives.
START_CLIP_FLAG = "--start-clip"

#: Both captions, which a host resolves this window by (with the process pid),
#: the way it resolves each satellite player by its own.  The plain one is what
#: the window wears; the second is what it wears while its HUD is over the main
#: player's video, and a host that knew only the first would lose the window
#: the moment the HUD went on.
TITLE_FLAG = "--title"
VIDEO_TITLE_FLAG = "--video-title"
WINDOW_TITLE = "Genau"
VIDEO_WINDOW_TITLE = "Video Main Player+Genau"

#: What sits beside the folder of clips this app plays: the pile a condemned
#: clip is moved to, and the decoded-frame cache.  Read off the rule itself
#: (``player_core.clip_folder``) rather than typed, because the app that
#: DELIVERS those clips drains that same pile and had the rule written out a
#: second time on its own side.
CONDEMNED_DIRNAME = weird_dir_for_clips_folder(Path("clips")).name
FRAME_CACHE_DIRNAME = cache_dir_for_clips_folder(Path("clips")).name

#: At the checkout root beside the launchers, which is the path a host that
#: resolves this checkout at all already has.
CONTRACT_FILE = "genau_contract.json"

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _file_flags() -> tuple[str, ...]:
    return tuple(f"--{name}" for name in SESSION_FILES)


def _rect_flags() -> tuple[str, ...]:
    return tuple(f"--{field}" for field in RECT_FIELDS)


def required_flags() -> tuple[str, ...]:
    """The flags every host launch carries, in the order a host writes them.

    Required in the strict sense: :func:`refuse_an_incomplete_host_launch` stops
    a launch missing one.  That is the half argparse cannot see -- an unknown
    flag it already refuses, while a flag a host stopped sending simply took the
    default this app would have used on its own.
    """
    return (
        CONFIG_FLAG,
        CLIPS_FOLDER_FLAG,
        *_rect_flags(),
        ICON_FLAG,
        HOSTED_FLAG,
        TITLE_FLAG,
        VIDEO_TITLE_FLAG,
        *_file_flags(),
    )


def host_launch_complaint(argv) -> str:
    """What is wrong with *argv* as a host's launch, or ``""`` when nothing is.

    A host launch is one carrying :data:`HOSTED_FLAG`; the desktop shortcut
    carries none of these and is left alone.  Said rather than raised so the
    caller can put it in the log before it goes -- a launch that dies before
    logging is configured leaves no word of why anywhere at all, which is the
    very failure a host's own suite had to grow a real launch to catch.
    """
    if HOSTED_FLAG not in argv:
        return ""
    missing = [flag for flag in required_flags() if flag not in argv]
    if not missing:
        return ""
    return (f"{MODULE}: a host launch must carry every flag "
            f"{CONTRACT_FILE} names; missing " + ", ".join(missing))


def add_host_arguments(parser: argparse.ArgumentParser, config) -> None:
    """Give *parser* every flag this document names, with the defaults a launch
    that names none falls back to."""
    parser.add_argument(CONFIG_FLAG, help="Path to a JSON config file.")
    parser.add_argument(CLIPS_FOLDER_FLAG, default=str(config.clips_dir))
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(ICON_FLAG, default=None,
                        help="The window icon a host hands over, so an Alt-Tab "
                             "entry says whose window this is")
    parser.add_argument(HOSTED_FLAG, default=None,
                        help="Group this window under the host's taskbar "
                             "button: its AppUserModelID")
    parser.add_argument(TITLE_FLAG, default=WINDOW_TITLE,
                        help="What this window calls itself")
    parser.add_argument(VIDEO_TITLE_FLAG, default=VIDEO_WINDOW_TITLE,
                        help="What it calls itself while its HUD is over the "
                             "main player's video")
    parser.add_argument("--command-file", default=str(config.genau_cmd_file))
    parser.add_argument("--paused-file", default=str(config.genau_paused_file))
    parser.add_argument("--console-file", default=None,
                        help="Poll this file for the console panel the host publishes")
    parser.add_argument("--drive-file", default=str(config.genau_drive_file),
                        help="Where to publish the drive readout for the main "
                             "player to draw in video mode")
    parser.add_argument("--status-file", default=str(config.genau_status_file),
                        help="Where to publish what the hand is doing")
    parser.add_argument("--dashboard-cmd-file", default=None,
                        help="Where a press on the console posts its host command")
    parser.add_argument(START_CLIP_FLAG, default=None,
                        help="Open on this clip rather than the top of the folder "
                             "-- how a host resumes the clip its last session left up")


def declaration() -> dict:
    """The published document, as a host reads it."""
    return {
        "module": MODULE,
        "hosted_flag": HOSTED_FLAG,
        "required_flags": list(required_flags()),
        "optional_flags": [START_CLIP_FLAG],
        "window_title": WINDOW_TITLE,
        "video_window_title": VIDEO_WINDOW_TITLE,
        "beside_the_clips_folder": {
            "condemned": CONDEMNED_DIRNAME,
            "frame_cache": FRAME_CACHE_DIRNAME,
        },
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    """Write the document out, in the shape the tracked copy holds."""
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
