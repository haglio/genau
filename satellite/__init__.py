"""A native FunTime satellite media player.

The two satellites (portrait + landscape) were VLC instances driven over VLC's
HTTP interface; this package replaces them with an in-process mpv-backed player,
the same way :mod:`nau` replaced the primary VLC.  It reuses genau's
:class:`nau.mpv_player.MpvPlayer` for GPU-decoded playback and owns its playlist
in Python, so navigation is deterministic and pausing is an in-process flag the
player simply obeys — no HTTP, no re-pause watchdog.
"""
