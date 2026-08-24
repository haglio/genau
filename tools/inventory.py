"""Reading the census of tests, and saying which of them stopped being collected."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


INVENTORY_RELATIVE_PATH = Path("tests") / "inventory.txt"

HEADER = """\
# Every test this suite collects, one node id per line.
#
# A test that stops being collected does not fail -- it stops existing, and the
# run stays green with a smaller number nobody reads. Renaming a method, its
# class or the file does exactly that, and leaves the body in place, so review
# sees a rename rather than a loss.
#
# Adding tests needs no edit here. Removing or renaming one does:
#     python -m tools.update_inventory                     # take on new tests
#     python -m tools.update_inventory --accept-removals   # ...and drop the gone
# and commit the result with the change that caused it, so the removal lands in
# the diff instead of hiding in a rewrite.

"""


def ids_in(text: str) -> set[str]:
    """The node ids written in an inventory file, one per line.

    Blank lines and ``#`` comments are skipped so the file can carry a header
    saying what it is and how to update it.
    """
    lines = (line.strip() for line in text.splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def missing_from(inventory: set[str], *, collected: set[str]) -> list[str]:
    """The ids the inventory has that this run did not collect, sorted.

    Sorted and complete rather than first-one-found: a rename takes a whole
    class or file at once, and being told about one of twenty is no use.
    Ids collected but absent from the inventory are not reported — adding
    tests has to stay free, or the file becomes something to fight.
    """
    return sorted(inventory - collected)


def changes(inventory: set[str], collected: set[str]) -> tuple[list[str], list[str]]:
    """What updating the inventory would do: ``(added, removed)``, both sorted.

    The two halves are kept apart because they are not the same act.  Adding is
    what a suite does as it grows and needs no thought; removing is a test that
    will never run again, and the updater makes the caller say so.
    """
    return sorted(collected - inventory), sorted(inventory - collected)


#: Environment this process may be carrying that would make the child answer
#: about something narrower than the whole suite, or resolve differently from
#: the way the gate resolves.
_NOT_INHERITED = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH")


def child_env(environ: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    """*environ* without the settings that would narrow or redirect the child.

    ``PYTEST_ADDOPTS`` is the dangerous one: a ``-k`` left in a shell comes back
    as most of the inventory missing, which is a red gate saying the opposite of
    what is true. ``PYTHONPATH`` goes for the reason the launch-smoke checks
    drop it -- so the child resolves the way the gate does, not the way a
    developer's shim does.
    """
    return {key: value for key, value in environ.items() if key not in _NOT_INHERITED}


def collect_ids(repo_dir: Path) -> set[str]:
    """Every node id pytest collects for *repo_dir*, asked in a child process.

    A child because the answer has to be the whole suite's, not this run's: a
    ``-k`` expression, a single file argument or a ``--deselect`` would
    otherwise leave most of the inventory looking missing.  See
    :func:`child_env` for what this process is not allowed to pass on.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(repo_dir), env=child_env(os.environ), capture_output=True, text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"collecting {repo_dir} exited {result.returncode}; the inventory cannot be "
            f"compared against a run that did not finish collecting:\n{result.stdout[-2000:]}"
        )
    return {line.strip() for line in result.stdout.splitlines() if "::" in line}
