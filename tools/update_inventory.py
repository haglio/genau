"""Rewrite tests/inventory.txt from what pytest collects right now.

Run this when a test is deliberately removed or renamed, and commit the result
alongside the change that caused it.  The point of the file is not that editing
it is hard -- it is that a test leaving the suite lands in the diff, in a file
that exists for nothing else, instead of hiding inside a rename or a rewrite.

    python -m tools.update_inventory                     # take on new tests
    python -m tools.update_inventory --accept-removals   # ...and drop the gone

Adding needs no argument.  Dropping does, because the case worth catching is the
one where the names about to go are not the ones you meant to touch.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.inventory import HEADER, INVENTORY_RELATIVE_PATH, changes, collect_ids, ids_in

REPO_DIR = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accept-removals", action="store_true",
        help="write the file even though tests it names are no longer collected",
    )
    args = parser.parse_args(argv)

    inventory_path = REPO_DIR / INVENTORY_RELATIVE_PATH
    inventory = ids_in(inventory_path.read_text(encoding="utf-8"))
    collected = collect_ids(REPO_DIR)
    added, removed = changes(inventory, collected)

    if removed and not args.accept_removals:
        print(f"{len(removed)} test(s) would leave the suite:", file=sys.stderr)
        print("  " + "\n  ".join(removed), file=sys.stderr)
        print(
            "\nIf every one of those is meant to go, run again with --accept-removals.\n"
            "If any of them is a rename you did not intend, that is what this is for.",
            file=sys.stderr,
        )
        return 1

    inventory_path.write_text(HEADER + "\n".join(sorted(collected)) + "\n", encoding="utf-8")
    print(f"{INVENTORY_RELATIVE_PATH}: {len(collected)} tests (+{len(added)}, -{len(removed)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
