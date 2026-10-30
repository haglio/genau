# Genau

This repository is retired. Genau plays flicks, short videos scrubbed to
wherever the OSR2 is as the Robot Hand drives it over T-Code, and every part of
it now lives in another repository:

- Its engine -- the flicks, the tick, the verbs it answers, the hand's driver --
  is in `funestra`.
- What runs it on Fun Time's Main Funestra is `fun_time`'s
  `main_funestra/genau.py`, and in the headset
  `fun_time_vr/genau_in_the_headset.py`. Fun Time starts the Main Funestra from
  its own venv.
- Its numbers (beats per loop, smoothing, sync strength, the flick cache,
  shuffle on load, and where the OSR2 broker publishes its beat) are the `genau`
  section of Fun Time's config, `fun_time_config.json`.
- The layout of its flicks folder -- a `2D` folder, a `VR` folder, and the
  `weird` folder beside them -- is `app_support.flick_folder`'s.

A change to Genau belongs in one of those.
