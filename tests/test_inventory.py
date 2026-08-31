"""The suite's own census: every test we had is still a test we run.

A test that stops being collected does not go red — it stops existing, and the
run ends green with a smaller number nobody is reading. Renaming a method, its
class, or the file does that, and the body stays in the file, so the diff a
reviewer sees is one word rather than a loss. It has already cost this family
coverage once: evolver's sanitize-guard tests were rewritten into unittest and
four cases went missing in the rewrite.

So the ids are written down. Adding tests stays free; a test that disappears
fails this until ``tests/inventory.txt`` is updated in the same commit, where it
reads in review as the removal it is.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.inventory import (
    changes,
    child_env,
    collect_ids,
    ids_in,
    is_one_of_this_repos_tests,
    missing_from,
)

REPO_DIR = Path(__file__).resolve().parent.parent
INVENTORY = REPO_DIR / "tests" / "inventory.txt"


class TestReadingTheInventory:
    def test_it_takes_one_id_per_line(self):
        assert ids_in("a::b\nc::d\n") == {"a::b", "c::d"}

    def test_it_ignores_blank_lines_and_comments(self):
        assert ids_in("# a census\n\na::b\n\n") == {"a::b"}


class TestWhichCollectedIdsAreThisRepos:
    """A plugin may hand the session a test module from outside this tree.

    ``app_support.sanitize.pytest_plugin`` does exactly that -- it appends the
    shipped tracked-tree check -- and pytest reports a file outside the rootdir
    by absolute path. Writing one of those into the census would pin the file to
    wherever this machine happens to have installed the package, and every other
    machine would then report it missing.
    """

    def test_an_id_inside_the_tree_counts(self):
        assert is_one_of_this_repos_tests("tests/test_inventory.py::test_it")

    def test_an_absolute_posix_id_does_not(self):
        assert not is_one_of_this_repos_tests(
            "/venv/lib/app_support/sanitize/test_tracked_tree.py::test_it")

    def test_an_absolute_windows_id_does_not(self):
        """windows-latest is the authority here, and it reports the other shape."""
        assert not is_one_of_this_repos_tests(
            "C:\\hostedtoolcache\\app_support\\sanitize\\test_tracked_tree.py::test_it")

    def test_an_id_with_no_path_at_all_does_not(self):
        """What pytest actually prints for the shipped check on this machine --
        the whole path is gone and only the test name is left."""
        assert not is_one_of_this_repos_tests("::test_no_blocklisted_terms_in_the_tracked_tree")

    def test_an_id_that_walks_up_out_of_the_tree_does_not(self):
        assert not is_one_of_this_repos_tests(
            "../app_support/app_support/sanitize/test_tracked_tree.py::test_it")


class TestComparingAgainstWhatWasCollected:
    def test_nothing_missing_when_the_run_holds_every_id(self):
        assert missing_from({"a::b"}, collected={"a::b", "c::d"}) == []

    def test_a_test_that_stopped_being_collected_is_named(self):
        assert missing_from({"a::b", "c::d"}, collected={"a::b"}) == ["c::d"]

    def test_every_missing_id_is_named_and_in_a_stable_order(self):
        """A run that lost a file loses many at once; naming one is no use."""
        gone = missing_from({"z::1", "a::1", "m::1"}, collected=set())

        assert gone == ["a::1", "m::1", "z::1"]


class TestTheLiveCensus:
    def test_every_test_the_inventory_names_is_still_collected(self):
        """The gate itself, asked of a run of its own.

        Collected in a child rather than read off this session, so the answer
        does not change with how this run was invoked -- a ``-k`` or a single
        file argument would otherwise make almost every id look missing.
        """
        gone = missing_from(ids_in(INVENTORY.read_text(encoding="utf-8")),
                            collected=collect_ids(REPO_DIR))

        assert not gone, (
            f"{len(gone)} test(s) in {INVENTORY.name} are no longer collected. If that is "
            f"deliberate, run tools/update_inventory.py and let the removals show in the diff:\n  "
            + "\n  ".join(gone)
        )


class TestUpdatingTheInventory:
    """Adding is free; removing has to be said out loud.

    The objection this answers is the obvious one: an agent confident enough to
    delete a test is confident enough to regenerate the file that noticed. It
    cannot stop that, and is not meant to — but a rename nobody intended shows
    up here as names the agent did not mean to touch, and it has to say so.
    """

    def test_new_tests_are_just_added(self):
        added, removed = changes({"a::b"}, collected={"a::b", "c::d"})

        assert (added, removed) == (["c::d"], [])

    def test_a_test_that_went_missing_is_reported_separately(self):
        added, removed = changes({"a::b", "c::d"}, collected={"a::b"})

        assert (added, removed) == ([], ["c::d"])

    def test_a_rename_reads_as_both_halves(self):
        """The half that matters is the removal; the addition alone would look
        like ordinary growth."""
        added, removed = changes({"a::old"}, collected={"a::new"})

        assert (added, removed) == (["a::new"], ["a::old"])


class TestAskingTheChildCleanly:
    """The child has to be asked about the whole suite, not this shell's idea of it.

    ``PYTEST_ADDOPTS`` is inherited, and a ``-k`` left in it would come back as
    almost every test in the inventory looking missing -- a red gate saying the
    exact opposite of what is true.
    """

    def test_the_filters_this_shell_carries_are_left_behind(self):
        env = child_env({"PYTEST_ADDOPTS": "-k tray", "PYTHONPATH": "/shim", "HOME": "/here"})

        assert "PYTEST_ADDOPTS" not in env
        assert "PYTHONPATH" not in env
        assert env["HOME"] == "/here"

    def test_a_filter_in_the_environment_does_not_shrink_the_census(self, monkeypatch):
        monkeypatch.setenv("PYTEST_ADDOPTS", "-k a_name_no_test_here_has")

        still_there = missing_from(ids_in(INVENTORY.read_text(encoding="utf-8")),
                                   collected=collect_ids(REPO_DIR))

        assert still_there == []


class TestACollectionThatDidNotFinish:
    def test_it_refuses_to_answer_rather_than_answer_short(self, tmp_path):
        """A truncated census is worse than none: written to the file it would
        drop exactly the tests whose absence it exists to notice."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_fine.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        (tests / "test_broken.py").write_text("import no_such_module_anywhere\n", encoding="utf-8")

        with pytest.raises(RuntimeError, match="did not finish collecting"):
            collect_ids(tmp_path)
