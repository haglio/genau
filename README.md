# Genau

Genau plays flicks, short videos scrubbed to wherever the OSR2 is as the Robot Hand
drives it over T-Code. It runs on Fun Time's Main Funestra (`../fun_time`):
Kino and Genau take turns on it, and Fun Time's mode switch tells it which of
the two to show. Genau's engine -- the
flicks, the tick, the verbs it answers, the hand's driver -- lives in
`../funestra`; what runs it on the Main
Funestra is `fun_time`'s `main_funestra/genau.py`, and in the headset
`fun_time_vr/genau_in_the_headset.py`.

This repo ships no code of its own. It holds Genau's settings and the layout of
its flicks folder; Fun Time starts the Main Funestra from its own venv.

## Genau's settings

`genau_config.json` is git-ignored -- it is his. `genau_config.example.json` is
its committed template: a `genau` section with the numbers the engine is tuned
with (beats per loop, smoothing, sync strength, the flick cache, shuffle on load)
and where the OSR2 broker publishes its beat. Fun Time hands the file to the
Main Funestra on every launch (`--genau-config`); everything else Genau needs --
the flicks folder, the files of its channel -- Fun Time names on that same
command line.

The flicks folder holds a `2D` folder, whose flicks the Main Funestra plays, and a
`VR` folder, whose flicks only the headset plays; a flick marked weird moves to
the same place in the `weird` folder beside the flicks folder. What the folder
is called on disk is his, and Fun Time names it on the command line.
`genau_contract.json` says so for the apps that fill the folder (Evolver holds
its delivery and its condemned pile to it), and `tests/test_genau_contract.py`
holds the document to `funestra.flick_folder`, where the layout is decided.
Each section is there twice, under its name from before the rename too
(`inside_the_clips_folder`, `beside_the_clips_folder`), until no checkout of
Evolver or Genaumacher reads those.

## The orchestrator channel

Genau still receives and publishes on files of its own in Fun Time's state
directory, beside the Main Funestra's: `genau_cmd.txt` (Fun Time writes, Genau
drains -- one verb per line, the set in `funestra.genau_controls`),
`genau_paused.txt` (whether the room is paused), `genau_status.txt` (what the
hand is doing: human-inspired motion, lock, flick, shape, which arrows are
at their limits) and `genau_drive.txt` (the drive readout the console draws).
Every verb and every field name is a contract between `funestra` and
`fun_time`, gated in those repos.

## Running the tests

This repo's venv runs nothing but its own checks, which hold
`genau_contract.json` to `funestra.flick_folder`, so `pyproject.toml` names
`funestra` at a tag, with `app_support` and `shared_ui` beside it. Install every
sibling with `--config-settings editable_mode=compat`, and this repo the same
way:

```
.venv/Scripts/python.exe -m pip install -e ../funestra --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e ../app_support --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools' default editable install resolves a sibling's submodules
through a meta-path finder pointed at that sibling's main checkout, so a
worktree a session names is half-shadowed: a module edited there keeps
resolving to the main tree.

```
.venv/Scripts/python.exe -m pytest tests/ -v
```
