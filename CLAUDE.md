# Genau

## Running tests

Always use the project venv — several dependencies (`pygame-ce`, `opencv-python`) are not installed system-wide and will cause import errors if you use the bare `python` interpreter.

```bash
"C:/path/to/suite-root/projects/genau/.venv/Scripts/python.exe" -m pytest tests/ -v
```

In a worktree, the `.venv` does not exist locally — use the absolute path above (it points to the main repo's venv, which is fine for running tests).

## The shared repos

None of these apps may reach into another's repo. What they share lives in
siblings installed editable into this venv, and a change to any of it belongs
there, not here: `../player_core` (playback engine, playlist format, the
orchestrator's command/paused file channel, the status writer), `../app_support`
(logging setup and exception hooks, `start_daemon_thread`,
`preparse_config_path`, `hidden_subprocess_kwargs`), `../shared_ui` (Qt widgets).

**Install each with `--config-settings editable_mode=compat`**, and this repo the
same way:

```bash
"…/genau/.venv/Scripts/python.exe" -m pip install -e ../player_core --config-settings editable_mode=compat
"…/genau/.venv/Scripts/python.exe" -m pip install -e ../app_support --config-settings editable_mode=compat
"…/genau/.venv/Scripts/python.exe" -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools' default editable install resolves submodules through a
meta-path finder pointed at the **main checkout**, so a worktree's own `nau/`
and `genau/` are half-shadowed: a module you deleted or edited there keeps
resolving to the main tree, and the suite goes green on code you are not
running. `player_core`'s `tests/test_install.py` catches its half of this.

## Test fixtures must be fabricated, never copied from the real library

Every fixture value that stands in for library data — a video title, a filename,
a performer or studio name, prompt text — must be **invented**. Never paste a
real one out of the media library to make a test feel realistic.

This is not a style note. It is the single thing that has actually leaked private
data into these repos: an agent writing a test reached for a real filename or
performer name because it was handy, and it rode into a public commit. Nothing in
the app's *design* pulls library text into source — the library lives outside
every repo, read at runtime through the git-ignored overlays — so this habit is
the only remaining path for a real name to get committed, and the only thing
stopping it is you following this rule.

Do not lean on the sanitize guard to catch it. `tools/sanitize_guard.py` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.

## Showing him a branch before it lands

A genau branch can be judged in a real session first: fun_time's
branch-verification flow (fun_time/CLAUDE.md, "Get his eyes on the branch") runs
Genau and Nau out of the checkouts a fun_time worktree names in its own
`state/genau_project_dirs.txt`. The laws about that chain live there — prove the
chain at handoff time (`--shortcut` prints the checkouts the next launch will
carry), never write checkout pins into his real config, and name a player_core
checkout beside yours only when that repo changed too.

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
