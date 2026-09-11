"""Whose taskbar button these windows belong to.

Genau is a window of the application the user actually launched, so Fun Time
passes its own AppUserModelID and it takes that — without stamping
anything, since the pin carrying that identity is Fun Time's to keep up to date.
"""
from __future__ import annotations

# ``genau.app`` is imported inside the tests, not here: importing it at collection
# time pulls pygame in for real before the view tests get to replace it with a
# mock, and 23 of them go red inside pygame's own resource lookup.  By the time
# these run, those have.


def _preparse():
    from genau.app import _preparse_taskbar_identity
    return _preparse_taskbar_identity


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

    def test_no_flag_names_no_identity(self):
        preparse = _preparse()

        assert preparse(["--fun-time"]) is None
        assert preparse([]) is None

    def test_a_value_that_merely_mentions_the_flag_is_not_one(self):
        """Only the spellings argparse itself accepts count."""
        assert _preparse()(["--start-clip", "--taskbar-identity-ish"]) is None

    def test_a_flag_with_nothing_after_it_names_no_identity(self):
        assert _preparse()(["--taskbar-identity"]) is None
