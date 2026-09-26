"""The document this repo publishes about its launch, held against the code.

A host starts this app with sixteen flags and then finds its window by the
caption it wears.  It cannot import this package, so every one of those names
was spelled on its own side as well, with nothing comparing the two: a flag the
host STOPPED sending fell through to a default -- a status file published where
that host was not reading, a paused flag nobody set -- with both suites green.

``genau_contract.json`` at the checkout root is how they travel now.  These
hold the document to the parser, to the window, and to the folder a condemned
clip goes to.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_core.clip_folder import cache_dir_for_clips_folder, weird_dir_for_clips_folder

from genau import host_contract as contract
from genau.window import hud_window_identity

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_tracked_copy_is_what_publishing_writes(tmp_path):
    """Run ``genau.host_contract.publish()`` when this fails: a document that
    has drifted from this module tells a host something untrue."""
    tracked = contract.contract_path(REPO_ROOT)

    assert (contract.publish(tmp_path).read_text(encoding="utf-8")
            == tracked.read_text(encoding="utf-8"))


def test_the_parser_accepts_every_flag_the_document_names():
    """A flag the document names and the parser refuses kills a host's launch in
    argparse before this app can log a word."""
    document = _document()
    parser = argparse.ArgumentParser()
    contract.add_host_arguments(parser)

    accepted = {option for action in parser._actions
                for option in action.option_strings} - {"-h", "--help"}

    assert {*document["required_flags"], *document["optional_flags"]} == accepted


def test_a_host_launch_short_of_a_required_flag_is_complained_about():
    """The half argparse cannot see.  An unknown flag it already refuses; a flag
    a host STOPPED sending used to be a silent default -- a status file
    published where that host was not reading it."""
    required = contract.required_flags()

    assert contract.host_launch_complaint(
        [word for flag in required for word in (flag, "7")]) == ""

    for left_out in required:
        short = [word for flag in required if flag != left_out
                 for word in (flag, "7")]

        assert left_out in contract.host_launch_complaint(short)


def test_a_launch_that_carries_none_of_the_hosts_flags_is_refused_too():
    """Genau runs only inside Fun Time.  The desktop shortcut that once started
    it on its own is gone, so a launch with nothing a host sends is a mistake
    to name in the log, not a way of running."""
    complaint = contract.host_launch_complaint([])

    assert all(flag in complaint for flag in contract.required_flags())


def test_the_captions_the_document_names_are_the_ones_this_window_wears():
    """A host resolves this window BY its caption, and loses it the moment the
    HUD renames it if it knows only the first."""
    document = _document()
    plain, video = document["window_title"], document["video_window_title"]

    assert hud_window_identity(False, base_title=plain, video_title=video) == plain
    assert hud_window_identity(True, base_title=plain, video_title=video) == video


def test_what_the_document_says_sits_beside_the_clips_folder_is_what_does():
    """The app that DELIVERS those clips drains the condemned pile, and had this
    rule written out a second time on its own side."""
    beside = _document()["beside_the_clips_folder"]
    clips = Path("a-library") / "clips"

    assert weird_dir_for_clips_folder(clips) == clips.parent / beside["condemned"]
    assert cache_dir_for_clips_folder(clips) == clips.parent / beside["frame_cache"]
