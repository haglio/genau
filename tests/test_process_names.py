"""Each app in this repo says its own name in the Windows task list.

Three apps share one venv, so a plain ``pythonw.exe`` puts all three in the task
list as the same anonymous "Python" -- and beside every other Python app on the
machine.  Windows takes what it shows about a process from the file it was
started from, so each app starts through a copy of the interpreter named and
described for it, made by ``app_support.process_identity``.

Naming a process on the way in is the one thing that cannot be done: writing the
copy takes the very interpreter being named.  So each run prepares the copy for
the run after and the launcher picks it up when it is there -- which is why both
halves are asserted here.  A launcher that never looks, or an app that never
prepares, leaves the app anonymous for good.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.process_identity import ProcessNamer

PROJECT_DIR = Path(__file__).resolve().parent.parent

# app name, role, icon, entry point, launcher
APPS = [
    ("Genau", "Genau", "genau_icon.ico", "genau/app.py", "launch.vbs"),
    ("Nau", "Nau", "nau_icon.ico", "nau/app.py", "launch_nau.vbs"),
    ("Genau VR", "GenauVR", "genau_vr_icon.ico", "genau_vr/app.py", "launch_vr.vbs"),
]


@pytest.mark.parametrize("app,role,icon,entry,launcher", APPS, ids=[a[0] for a in APPS])
def test_the_launcher_prefers_the_copy_named_for_its_app(
    app: str, role: str, icon: str, entry: str, launcher: str,
):
    text = (PROJECT_DIR / launcher).read_text(encoding="utf-8")
    expected = ProcessNamer(app).exe_name("pythonw.exe", role)

    assert expected in text, f"{launcher} does not look for {expected}"
    assert "If fso.FileExists(namedPython) Then venvPython = namedPython" in text


@pytest.mark.parametrize("app,role,icon,entry,launcher", APPS, ids=[a[0] for a in APPS])
def test_the_app_prepares_that_copy_for_next_time(
    app: str, role: str, icon: str, entry: str, launcher: str,
):
    text = (PROJECT_DIR / entry).read_text(encoding="utf-8")

    assert "_name_this_process" in text
    assert f'ProcessNamer("{app}"' in text
    assert f'prepare_launcher("{role}")' in text


@pytest.mark.parametrize("app,role,icon,entry,launcher", APPS, ids=[a[0] for a in APPS])
def test_each_app_stamps_its_own_mark(
    app: str, role: str, icon: str, entry: str, launcher: str,
):
    """Not a shared one: the point of the row is telling these three apart, and
    they share a venv, so the icon has to come from each app's own file."""
    assert (PROJECT_DIR / icon).is_file(), f"{icon} is missing"
    assert icon in (PROJECT_DIR / entry).read_text(encoding="utf-8")


@pytest.mark.parametrize("app,role,icon,entry,launcher", APPS, ids=[a[0] for a in APPS])
def test_the_row_reads_as_the_app_and_nothing_more(
    app: str, role: str, icon: str, entry: str, launcher: str,
):
    """The Processes tab shows this string, and each of these apps is one app
    with one window -- so the row is its name, not its name said twice."""
    assert ProcessNamer(app).description(role) == app


def test_the_three_apps_cannot_collide_on_one_file_name():
    """Sharing a venv means sharing the directory the copies land in."""
    names = {ProcessNamer(app).exe_name("pythonw.exe", role) for app, role, *_ in APPS}

    assert len(names) == len(APPS), f"two apps want the same file: {sorted(names)}"


def test_naming_never_takes_a_launch_down():
    """Every call site swallows failure, because a read-only venv or an
    antivirus hold must cost the name in the task list and nothing else."""
    for _, _, _, entry, _ in APPS:
        text = (PROJECT_DIR / entry).read_text(encoding="utf-8")
        body = text[text.index("def _name_this_process"):]
        body = body[:body.index("\ndef ", 1)]
        assert "except Exception:" in body, f"{entry} lets a naming failure escape"
