# Genau — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file holds only what
is particular to this repo.

## What this repo is

Genau runs on Fun Time's Main Funestra (`../fun_time`: `main_funestra/genau.py`
on the desktop, `fun_time_vr/genau_in_the_headset.py` in the headset) over the
engine in `../player_core`. This repo ships no code: it is the venv the Main
Funestra runs out of, pinned to the `player_core` it was built against, and the home
of Genau's settings (`genau_config.json`, with `genau_config.example.json` as its
template) and of the flicks-folder layout it promises the apps that fill the
folder (`genau_contract.json`). A change to Genau belongs in one of those two
repos.

## Running tests

Always use the project venv:

```bash
"…/genau/.venv/Scripts/python.exe" -m pytest tests/ -v
```

In a worktree the `.venv` does not exist locally — use the main checkout's.

## Installing

Every sibling, and this repo, with `--config-settings editable_mode=compat`:

```bash
"…/genau/.venv/Scripts/python.exe" -m pip install -e ../player_core --config-settings editable_mode=compat
"…/genau/.venv/Scripts/python.exe" -m pip install -e ../app_support --config-settings editable_mode=compat
"…/genau/.venv/Scripts/python.exe" -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools' default editable install resolves a sibling's submodules
through a meta-path finder pointed at the **main checkout**, so a worktree a
session names is half-shadowed: a module edited there keeps resolving to the
main tree. `player_core`'s `tests/test_install.py` catches its half of this.

## Moving the player_core pin

The Main Funestra imports `funestra_core` out of this venv, so a Fun Time
change that needs a new name from it lands in this order: `player_core` tags a
version, this repo takes the tag and the venv is reinstalled, then Fun Time's
own pin moves (fun_time/CLAUDE.md says the same from its side).

## Landing — GitHub merge queue, not local ff-merge

This repo is public at `github.com/haglio/genau` with a merge-queue ruleset on
`main`, so the global "ff-merge into the primary checkout under
`.git/agent-merge.lock`" flow does NOT apply here:

- **Land through a pull request.** From your worktree: commit, `git fetch origin
  && git rebase origin/main`, `git push -u origin <branch>`, then
  `gh pr create --fill`. Auto-merge arms itself; the queue rebases your PR onto
  `main`, runs the required check, and merges it when green. Don't ff-merge into
  the primary checkout, don't push `main` directly, and never force-push `main`.
- **The `.git/agent-merge.lock` is retired here** — the GitHub queue serializes.
- **Sync local checkouts by pulling.** `main` advances only on origin (via the
  queue), so the primary checkout and worktrees update with
  `git pull --ff-only origin main`; the running app self-updates the same way.
  The primary is only ever fast-forwarded — never reset or merged-into.
- **A red required check** (`.github/workflows/merge-gate.yml`) can't land.

Everything else in the global CLAUDE.md — work in a worktree, green tests before
you push, clean handoff — still applies.
