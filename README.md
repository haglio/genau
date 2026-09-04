# Genau

Three clip players that share one repo, one config file and one command
vocabulary.

| App | Module | Launcher | What it is |
| --- | --- | --- | --- |
| **Genau** | `genau/` | Fun Time | A pygame window that plays short clips and drives an OSR2 with the Robot Hand over T-Code, scrubbing the clip to wherever the device is. |
| **Nau** | `nau/` | Fun Time | A full-length player with a playlist, funscript playback and the console the family's drive readout is drawn on. |
| **GenauVR** | `genau_vr/` | `launch_vr.vbs` | The same idea in a headset: VR180 clips on a sphere, driven by the same stroke arithmetic. |

GenauVR runs standalone; Genau and Nau run only as windows inside **Fun Time**,
the orchestrator in a sibling repo. Which of the two owns the main slot is Fun
Time's decision, and both are told so over the file channel below.

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
the main checkout, so a worktree's own `genau/` and `nau/` are half-shadowed: a
module you edited there keeps resolving to the main tree, and the suite goes
green on code you are not running.

`vendor/` holds the libmpv binary Nau needs; it is fetched locally and never
committed.

## Configuring

`genau_config.json` is git-ignored — it names real paths on a real machine.
`genau_config.example.json` is its committed template and documents every key:
`clips_dir`, `vr_clips_dir`, `state_dir`,
and a `genau` and a `nau` section for each player's own settings.

Relative paths in it are resolved against the config file, not against whatever
directory a shortcut happened to start the app in.

## The orchestrator channel

Four files in `state_dir`, and they are a contract with Fun Time rather than an
internal detail. Genau **receives** on the first two and **publishes** the last
two:

| File | Direction | What it carries |
| --- | --- | --- |
| `genau_cmd.txt` | Fun Time writes, Genau drains | One verb per line — `PAUSE`, `SPEED 90`, `HUD_ON`. The accepted set is `genau/controls.py`. |
| `genau_paused.txt` | Fun Time writes, Genau polls | Whether the room is paused, while the broker is driving. |
| `genau_status.txt` | Genau writes, Fun Time reads | What the hand is doing: cruise, lock, clip, shape, and which arrows are at their limits. |
| `genau_drive.txt` | Genau writes, Nau reads | The drive readout, so Nau's console can draw the numbers Genau is driving with. |

**Every verb string and every status field name is a contract.** Renaming one
breaks the orchestrator with no error on either side — an unknown verb is logged
and ignored, and a renamed field reads as absent. `tests/test_genau_vocabulary.py`
writes both sets down and gates them from two sides, so a change to either has
to be a deliberate line in a diff.

## Adding a control

One record in `genau/controls.py`:

```python
Control(
    name="speed",
    needs=("robot_hand",),
    verbs=(
        Verb("SPEED_DOWN", _stepper(-5), key="K_j"),
        Verb("SPEED_UP", _stepper(5), key="K_l"),
        Verb("SPEED", _number_setter(set_speed), takes_a_value=True),
    ),
)
```

That is the verb the orchestrator sends, the key the window answers to, and what
the control cannot act without — in one place. The dispatcher, the key handler
and the wiring all read it; none of them needs editing.

## Running the tests

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

`tests/inventory.txt` lists every test the suite collects. Adding tests needs no
edit; removing or renaming one does, so a test that stops running has to be named
in the same commit:

```
python -m tools.update_inventory                     # take on new tests
python -m tools.update_inventory --accept-removals   # ...and drop the gone
```
