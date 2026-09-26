# Genau

A pygame window around the family's clip player: short clips, scrubbed to
wherever the OSR2 is as the Robot Hand drives it over T-Code.

It runs only as a window inside **Fun Time**, the orchestrator in a sibling
repo, sharing the main slot with Fun Time's own main player. Which of the two
owns the slot is Fun Time's decision, and both are told so over the file
channel below. Genau's engine -- the clips, the tick, the
verbs it answers, the hand's driver -- lives in `../player_core`, because Fun
Time's VR session runs the same engine in-process for its genau mode; what is
here is the window.

## Installing

Everything shared with the rest of the family lives in sibling repos installed
editable into this venv: `player_core` (playback, the file channel, the status
writer), `app_support` (logging, threading, CLI preparsing) and `shared_ui`
(design tokens and the family's icon geometry).

**Install every one of them with `--config-settings editable_mode=compat`, this
repo included:**

```
.venv/Scripts/python.exe -m pip install -e ../player_core --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e ../app_support --config-settings editable_mode=compat
.venv/Scripts/python.exe -m pip install -e . --config-settings editable_mode=compat
```

Without it, setuptools resolves submodules through a meta-path finder pointed at
the main checkout, so a worktree's own `genau/` is half-shadowed: a
module you edited there keeps resolving to the main tree, and the suite goes
green on code you are not running.

## Configuring

`genau_config.json` is git-ignored — it names real paths on a real machine.
`genau_config.example.json` is its committed template and documents every key:
`state_dir`, where the logs go, and a `genau` section for Genau's own settings.
Everything else -- the clips folder, the window's rect and captions, and the
files of the channel below -- Fun Time names on the command line of every
launch, and a launch that leaves one out is refused.

Relative paths in it are resolved against the config file, not against whatever
directory a shortcut happened to start the app in.

## The orchestrator channel

Four files in `state_dir`, and they are a contract with Fun Time rather than an
internal detail. Genau **receives** on the first two and **publishes** the last
two:

| File | Direction | What it carries |
| --- | --- | --- |
| `genau_cmd.txt` | Fun Time writes, Genau drains | One verb per line — `PAUSE`, `SPEED 90`, `HUD_ON`. The accepted set is `player_core.genau_controls`. |
| `genau_paused.txt` | Fun Time writes, Genau polls | Whether the room is paused, while the broker is driving. |
| `genau_status.txt` | Genau writes, Fun Time reads | What the hand is doing: cruise, human-inspired motion, lock, clip, shape, and which arrows are at their limits. |
| `genau_drive.txt` | Genau writes, the main player reads | The drive readout, so the main player's console can draw the numbers Genau is driving with. |

**Every verb string and every status field name is a contract.** Renaming one
breaks the orchestrator with no error on either side — an unknown verb is logged
and ignored, and a renamed field reads as absent. `tests/test_genau_vocabulary.py`
writes both sets down and gates them from two sides, so a change to either has
to be a deliberate line in a diff.

## Adding a control

One record in `player_core/genau_controls.py`, and one line in this repo's
`tests/test_genau_vocabulary.py` saying it is now part of the contract:

```python
Control(
    name="speed",
    needs=("robot_hand",),
    verbs=(
        Verb("SPEED_DOWN", _stepper(-5)),
        Verb("SPEED_UP", _stepper(5)),
        Verb("SPEED", _number_setter(set_speed), takes_a_value=True),
    ),
)
```

That is the verb the orchestrator sends and what the control cannot act without,
in one place. The dispatcher and the wiring both read it; neither needs editing.
The window answers no keys of its own: Fun Time's hotkeys are the keyboard for
the whole room, and a key reaches Genau as the verb Fun Time sends for it.

## Running the tests

```
.venv/Scripts/python.exe -m pytest tests/ -v
```
