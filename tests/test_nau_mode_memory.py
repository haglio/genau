"""The mode Nau was last in, kept across sessions."""
from __future__ import annotations

from nau.library import FULL, MIXED, SHORTS
from nau.mode_memory import ModeMemory, RememberedMode


class TestLengthMode:
    def test_a_written_mode_reads_back(self, tmp_path):
        """Fun Time resumes the playlist a session closed on, so the mode that
        chose those videos has to survive the session too."""
        path = tmp_path / "state" / "nau_mode.txt"

        ModeMemory(path).write(RememberedMode(length_mode=SHORTS))

        assert ModeMemory(path).read().length_mode == SHORTS

    def test_nothing_remembered_reads_empty(self, tmp_path):
        assert ModeMemory(tmp_path / "never_written.txt").read() == RememberedMode()

    def test_a_later_write_replaces_the_earlier_one(self, tmp_path):
        memory = ModeMemory(tmp_path / "nau_mode.txt")

        memory.write(RememberedMode(length_mode=SHORTS))
        memory.write(RememberedMode(length_mode=FULL))

        assert memory.read().length_mode == FULL

    def test_a_mode_that_is_no_longer_a_mode_is_forgotten(self, tmp_path):
        """The file outlives the code that wrote it, so a word this build does
        not recognise must fall back rather than be handed to the library."""
        path = tmp_path / "nau_mode.txt"
        path.write_text("length_mode=wildly-obsolete\n", encoding="utf-8")

        assert ModeMemory(path).read().length_mode == ""

    def test_without_a_path_it_is_inert(self):
        """No state dir configured: nothing is remembered, and nothing raises."""
        memory = ModeMemory(None)

        memory.write(RememberedMode(length_mode=MIXED))

        assert memory.read() == RememberedMode()


class TestCompilation:
    def test_the_compilation_reads_back_with_the_mode(self, tmp_path):
        """Nau's playlist swap for a compilation is in memory only — the file
        Fun Time resumes never sees it — so being inside one is remembered here
        or not at all."""
        path = tmp_path / "nau_mode.txt"

        ModeMemory(path).write(RememberedMode(length_mode=SHORTS, compilation="Vol6"))

        assert ModeMemory(path).read() == RememberedMode(length_mode=SHORTS, compilation="Vol6")

    def test_a_title_with_separators_in_it_survives(self, tmp_path):
        """Compilation titles carry dashes, spaces and parentheses; only the
        first "=" divides the line."""
        path = tmp_path / "nau_mode.txt"
        title = "various - Ultimate Example Studio Alpha Collection - Volume 6 (v1)"

        ModeMemory(path).write(RememberedMode(length_mode=MIXED, compilation=title))

        assert ModeMemory(path).read().compilation == title

    def test_leaving_a_compilation_is_remembered_too(self, tmp_path):
        path = tmp_path / "nau_mode.txt"
        memory = ModeMemory(path)
        memory.write(RememberedMode(length_mode=SHORTS, compilation="Vol6"))

        memory.write(RememberedMode(length_mode=SHORTS))

        assert memory.read().compilation == ""
