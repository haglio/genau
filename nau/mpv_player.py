"""libmpv-backed playback engine for Nau.

mpv hardware-decodes on the GPU end-to-end (d3d11va), so it plays HD/4K
smoothly where the old OpenCV-on-the-render-thread pipeline dropped frames.
It also owns audio (A/V sync for free), precise seeking (click-to-seek), and
native A/B looping — so this one object replaces the former VideoStream +
AudioPlayer + PlaybackClock trio.  mpv renders directly into the pygame
window (via ``wid``); Nau's overlays go on top through ``overlay_add``.

Not unit-tested: it needs the libmpv DLL and a real window.  The pure control
logic that drives it lives in :class:`nau.session.PlayerSession`, which is
tested against a fake exposing this same interface.
"""
from __future__ import annotations

from pathlib import Path

from .libmpv_loader import add_libmpv_to_path


def _import_mpv():
    add_libmpv_to_path()
    import mpv  # noqa: PLC0415 — must follow add_libmpv_to_path (DLL on %PATH%)

    return mpv


class MpvPlayer:
    def __init__(self, wid: int, *, muted: bool = False) -> None:
        mpv = _import_mpv()
        self._mpv = mpv.MPV(
            wid=str(int(wid)),
            vo="gpu",
            hwdec="auto-safe",
            # loop-1: the current file repeats (like the old primary VLC's
            # --repeat), so a video never ends on its own; [ ] navigates.
            loop_file="inf",
            keep_open="yes",
            mute="yes" if muted else "no",
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
        )

    def load(self, path: Path) -> None:
        self._mpv.play(str(path))

    @property
    def position_ms(self) -> float:
        return (self._mpv.time_pos or 0.0) * 1000.0

    @property
    def duration_ms(self) -> float:
        return (self._mpv.duration or 0.0) * 1000.0


    def set_paused(self, paused: bool) -> None:
        self._mpv.pause = paused

    def set_speed(self, speed: float) -> None:
        """Set the playback rate (1.0 = normal). mpv retimes video and audio,
        and its ``time_pos`` clock advances at this rate — so the session's
        funscript sync, which reads that clock, follows the new speed for free
        (the T-Code driver only rescales its move durations)."""
        self._mpv.speed = speed

    def set_volume(self, volume: int) -> None:
        """Set the audio volume (0-100, a percentage of the source's own level).

        ``volume`` and ``mute`` are independent mpv properties, so a player
        constructed muted (``--no-audio`` / ``FUN_TIME_MUTE_AUDIO``, which the
        hidden-desktop integration runs rely on) stays silent whatever is set here.
        """
        self._mpv.volume = volume

    def seek_ms(self, ms: float) -> None:
        self._mpv.command("seek", max(0.0, ms) / 1000.0, "absolute", "exact")

    def set_ab_loop(self, in_ms: float, out_ms: float) -> None:
        self._mpv.ab_loop_a = in_ms / 1000.0
        self._mpv.ab_loop_b = out_ms / 1000.0

    def clear_ab_loop(self) -> None:
        self._mpv.ab_loop_a = "no"
        self._mpv.ab_loop_b = "no"

    @property
    def eof(self) -> bool:
        return bool(self._mpv.eof_reached)


    def screenshot_bgra(self, height: int = 64):
        """Current displayed frame, resized to *height*, as a BGRA array.

        Used to capture loop in/out thumbnails on demand (a few times per
        loop) without disturbing playback — mpv renders the video itself.
        Returns None if no frame is available yet.
        """
        import numpy as np

        img = self._mpv.screenshot_raw()  # PIL Image
        if img is None or img.height == 0:
            return None
        w = max(1, round(height * img.width / img.height))
        arr = np.asarray(img.convert("RGBA").resize((w, height)))
        return np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]], dtype=np.uint8)

    def overlay(self, ident: int, x: int, y: int, rgba) -> None:
        """Composite an (H, W, 4) BGRA uint8 array at (x, y) over the video."""
        import numpy as np

        arr = np.ascontiguousarray(rgba, dtype=np.uint8)
        h, w = arr.shape[:2]
        self._mpv.overlay_add(
            ident, x, y, "&" + str(arr.ctypes.data), 0, "bgra", w, h, w * 4,
        )
        # hold a reference so the buffer isn't freed while mpv reads it
        self._overlays = getattr(self, "_overlays", {})
        self._overlays[ident] = arr

    def remove_overlay(self, ident: int) -> None:
        self._mpv.overlay_remove(ident)
        getattr(self, "_overlays", {}).pop(ident, None)

    def close(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass
