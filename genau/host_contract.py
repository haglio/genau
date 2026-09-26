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

#: The taskbar button this window is grouped under: Fun Time's, since Genau is
#: one window of the application the user launched.
TASKBAR_IDENTITY_FLAG = "--taskbar-identity"

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
    """The flags every launch carries, in the order a host writes them."""
    return (
        CONFIG_FLAG,
        CLIPS_FOLDER_FLAG,
        *_rect_flags(),
        ICON_FLAG,
        TASKBAR_IDENTITY_FLAG,
        TITLE_FLAG,
        VIDEO_TITLE_FLAG,
        *_file_flags(),
    )


def host_launch_complaint(argv) -> str:
    """What is wrong with *argv* as a host's launch, or ``""`` when nothing is.

    Every launch is a host's: Genau runs only inside Fun Time.  Said rather than
    raised so the caller can put it in the log before it goes -- a launch that
    dies before logging is configured leaves no word of why anywhere at all.
    """
    missing = [flag for flag in required_flags() if flag not in argv]
    if not missing:
        return ""
    return (f"{MODULE}: a host launch must carry every flag "
            f"{CONTRACT_FILE} names; missing " + ", ".join(missing))


def add_host_arguments(parser: argparse.ArgumentParser) -> None:
    """Give *parser* every flag this document names."""
    for flag in required_flags():
        parser.add_argument(flag, required=True,
                            type=int if flag in _rect_flags() else str)
    parser.add_argument(START_CLIP_FLAG, default=None)


def declaration() -> dict:
    """The published document, as a host reads it."""
    return {
        "module": MODULE,
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
