"""Whose taskbar button these windows belong to.

Standalone, each player is its own application and stamps its own pinned
shortcut.  Under an orchestrator they are windows of the application the user
actually launched, so it passes its own AppUserModelID and they take that —
without stamping anything, since the pin behind that identity is the
orchestrator's to keep up to date.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

# ``genau.app`` and ``nau.app`` are imported inside the tests, not here: importing
# either at collection time pulls pygame in for real before the view tests get to
# replace it with a mock, and 23 of them go red inside pygame's own resource
# lookup.  By the time these run, those have.


def _preparse():
    from genau.app import _preparse_taskbar_identity
    return _preparse_taskbar_identity


def _nau():
    from nau.app import _APP_USER_MODEL_ID, _set_aumid
    return _APP_USER_MODEL_ID, _set_aumid


class TestPreparseTaskbarIdentity:
    """Genau claims its identity before the parser runs — the full parser needs
    the loaded config, and the identity has to be taken before any window."""

    def test_it_reads_the_flag_in_either_spelling(self):
        preparse = _preparse()

        assert preparse(["--taskbar-identity", "Example.App"]) == "Example.App"
        assert preparse(["--taskbar-identity=Example.App"]) == "Example.App"

    def test_it_finds_the_flag_among_the_others(self):
        argv = ["--fun-time", "--width", "800", "--taskbar-identity", "Example.App", "--x", "0"]

        assert _preparse()(argv) == "Example.App"

    def test_no_flag_means_genau_is_its_own_application(self):
        preparse = _preparse()

        assert preparse(["--fun-time"]) is None
        assert preparse([]) is None

    def test_a_value_that_merely_mentions_the_flag_is_not_one(self):
        """Only the spellings argparse itself accepts count."""
        assert _preparse()(["--start-clip", "--taskbar-identity-ish"]) is None

    def test_a_flag_with_nothing_after_it_names_no_identity(self):
        assert _preparse()(["--taskbar-identity"]) is None


class TestNauTakesTheIdentityItIsGiven:
    def test_told_one_it_takes_it_and_stamps_nothing(self):
        """The pinned shortcut behind that identity is the orchestrator's."""
        _identity, set_aumid = _nau()

        with patch("player_core.taskbar.set_app_user_model_id") as claim, \
             patch("genau.win32.take_taskbar_identity") as own:
            set_aumid(Path("C:/example/genau_config.json"), "Example.App")

        claim.assert_called_once_with("Example.App")
        own.assert_not_called()

    def test_told_none_it_is_its_own_application(self):
        own_identity, set_aumid = _nau()

        with patch("player_core.taskbar.set_app_user_model_id") as claim, \
             patch("genau.win32.take_taskbar_identity") as own:
            set_aumid(Path("C:/example/genau_config.json"), None)

        claim.assert_not_called()
        assert own.call_args[0][0] == own_identity

    def test_a_refusal_never_stops_the_player_starting(self):
        """An icon is not worth failing to open a window over."""
        _identity, set_aumid = _nau()

        with patch("player_core.taskbar.set_app_user_model_id", side_effect=OSError):
            set_aumid(Path("C:/example/genau_config.json"), "Example.App")
