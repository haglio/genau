# Genau

Genau plays short clips scrubbed to wherever the OSR2 is as the Robot Hand
drives it over T-Code. It runs on Fun Time's Main Player (`../fun_time`): the
window is the Main Player's, Kino and Genau take turns on it, and Fun Time's
mode switch tells the window which of the two to show. Genau's engine -- the
clips, the tick, the verbs it answers, the hand's driver -- lives in
`../player_core`; what runs it on the Main Player is `fun_time`'s
`main_player/genau.py`, and in the headset `fun_time_vr/genau_role.py`.

This repo ships no code of its own. It is two things.

## The venv the Main Player runs out of

Fun Time launches the Main Player as `python -m main_player` out of this repo's
`.venv` (`paths.genau_python_exe` in its config), so `pyproject.toml` names what
that player imports: `player_core` at the tag the Main Player was built against,
with `app_support` and `shared_ui` beside it, and `pygame-ce`. A Fun Time change
that makes the Main Player import a new `player_core` name moves the pin here
first, and this venv is reinstalled, before Fun Time's own pin moves.

Install every sibling with `--config-settings editable_mode=compat`, and this
repo the same way:

```
.venv/Scripts/python.exe -m pip install -e ../player_core --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e ../app_support --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools' default editable install resolves a sibling's submodules
through a meta-path finder pointed at that sibling's main checkout, so a
worktree a session names is half-shadowed: a module edited there keeps
resolving to the main tree.

## Genau's settings

`genau_config.json` is git-ignored -- it is his. `genau_config.example.json` is
its committed template: a `genau` section with the numbers the engine is tuned
with (beats per loop, smoothing, sync strength, the clip cache, shuffle on load)
and where the OSR2 broker publishes its beat. Fun Time hands the file to the
Main Player on every launch (`--genau-config`); everything else Genau needs --
the clips folder, the files of its channel -- Fun Time names on that same
command line.

The clips folder holds a `2D` folder, whose clips the Main Player plays, and a
`VR` folder, whose clips only the headset plays; a clip marked weird moves to
the same place in the `weird` folder beside the clips folder.
`genau_contract.json` says so for the apps that fill the folder (Evolver holds
its delivery and its condemned pile to it), and `tests/test_genau_contract.py`
holds the document to `player_core.clip_folder`, where the layout is decided.

## The orchestrator channel

Genau still receives and publishes on files of its own in Fun Time's state
directory, beside the Main Player's: `genau_cmd.txt` (Fun Time writes, Genau
drains -- one verb per line, the set in `player_core.genau_controls`),
`genau_paused.txt` (whether the room is paused), `genau_status.txt` (what the
hand is doing: cruise, human-inspired motion, lock, clip, shape, which arrows are
at their limits) and `genau_drive.txt` (the drive readout the console draws).
Every verb and every field name is a contract between `player_core` and
`fun_time`, gated in those repos.

## Running the tests

```
.venv/Scripts/python.exe -m pytest tests/ -v
```
