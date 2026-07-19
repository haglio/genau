"""The length mode Nau was last in, kept across sessions."""
from __future__ import annotations

from nau.library import FULL, MIXED, SHORTS
from nau.mode_memory import ModeMemory


class TestModeMemory:
    def test_a_written_mode_reads_back(self, tmp_path):
        """Fun Time resumes the playlist a session closed on, so the mode that
        chose those videos has to survive the session too."""
        path = tmp_path / "state" / "nau_length_mode.txt"

        ModeMemory(path).write(SHORTS)

        assert ModeMemory(path).read() == SHORTS

    def test_nothing_remembered_reads_empty(self, tmp_path):
        assert ModeMemory(tmp_path / "never_written.txt").read() == ""

    def test_a_later_write_replaces_the_earlier_one(self, tmp_path):
        path = tmp_path / "nau_length_mode.txt"
        memory = ModeMemory(path)

        memory.write(SHORTS)
        memory.write(FULL)

        assert memory.read() == FULL

    def test_a_mode_that_is_no_longer_a_mode_is_forgotten(self, tmp_path):
        """The file outlives the code that wrote it, so a word this build does
        not recognise must fall back rather than be handed to the library."""
        path = tmp_path / "nau_length_mode.txt"
        path.write_text("wildly-obsolete\n", encoding="utf-8")

        assert ModeMemory(path).read() == ""

    def test_without_a_path_it_is_inert(self):
        """No state dir configured: nothing is remembered, and nothing raises."""
        memory = ModeMemory(None)

        memory.write(MIXED)

        assert memory.read() == ""
