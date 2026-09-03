"""GenauVR — VR180 clips on a sphere, driving the same device Genau does.

**How this package handles failure**, because the unit had four strategies for
one class of problem and no note saying which to reach for:

* **Startup** raises, and the caller turns it into the Win32 dialog a session
  launched from a shortcut has no other way to show.  Nothing here calls
  ``sys.exit``: under ``pythonw`` that is indistinguishable from a crash.
* **Cosmetic** paths log and carry on -- the window icon, the process name, the
  audio mixer.  A headset with no sound still shows the clip.
* **Per-frame** failures go through :class:`genau.tick_failures.TickFailures`,
  which says the first of each kind with its traceback and counts the rest.  A
  bare ``pass`` here is a fault that lasts a whole session with an empty log,
  which is how a thumbstick that had stopped answering went unreported.
"""
