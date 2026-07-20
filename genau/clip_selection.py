from __future__ import annotations

from pathlib import Path


class ClipSelectionController:
    def __init__(
        self,
        *,
        sequence,
        clip_store,
        loader,
        renderer,
        notifier,
        discard_clip=lambda _path: None,
    ):
        self.sequence = sequence
        self.clip_store = clip_store
        self.loader = loader
        self.renderer = renderer
        self.notifier = notifier
        self.discard_clip = discard_clip
        self._pending_path: Path | None = None

    @property
    def count(self) -> int:
        return self.sequence.count

    @property
    def current_number(self) -> int:
        return self.sequence.current_number

    @property
    def current_path(self) -> Path:
        return self.sequence.current_path

    @property
    def pending_clip_name(self) -> str | None:
        return self._pending_path.name if self._pending_path is not None else None

    def set_current_clip(self, path: Path) -> None:
        """Switch to a clip immediately, loading it if it isn't cached yet."""
        self._pending_path = None
        self._show(path)

        if path not in self.clip_store.clip_cache:
            self.loader.request_clip_load(path)
        if path in self.clip_store.clip_cache:
            self._prepare_active_clip()

    def step(self, delta: int) -> None:
        """Advance to next/prev clip.  If the clip is cached, switch
        immediately.  Otherwise keep the current clip playing and defer
        the switch until the new clip is loaded."""
        path = self.sequence.step(delta)

        if path in self.clip_store.clip_cache:
            self._switch_to(path)
            return

        # Defer — keep rendering the old clip while the new one loads
        self._pending_path = path
        self.loader.request_clip_load(path)

    def discard_current(self) -> bool:
        """Condemn the clip on screen and move on to the one behind it.

        Unlike :meth:`step` there is nothing to defer to: the condemned clip is
        on its way out of the folder, so the successor takes the screen at once
        even if it still has to be decoded.  Returns False, having done nothing,
        when it is the only clip left — Genau has to keep something on screen.
        """
        condemned = self.sequence.current_path
        successor = self.sequence.drop_current()
        if successor is None:
            return False

        self.discard_clip(condemned)
        self.clip_store.clip_cache.pop(condemned, None)
        self.set_current_clip(successor)
        return True

    def adopt_pending_clip(self) -> bool:
        """Called from the refresh loop.  If a deferred clip has finished
        loading, switch the renderer to it and return True."""
        if self._pending_path is None:
            return False
        if self._pending_path not in self.clip_store.clip_cache:
            return False

        self._switch_to(self._pending_path)
        return True

    def request_nearby_prefetch(self) -> None:
        if self.sequence.count <= 1 or self.loader.is_busy:
            return

        for candidate in self.sequence.nearby_candidates():
            if candidate not in self.clip_store.clip_cache and candidate not in self.clip_store.decoded_frame_cache:
                self.loader.request_prefetch(candidate)
                return

    def _show(self, path: Path) -> None:
        """Point the renderer at a clip and tell the world it is up."""
        self.renderer.set_current_clip_path(path)
        self.notifier.notify_clip(path)

    def _switch_to(self, path: Path) -> None:
        """Take up an already-cached clip, cancelling any deferred switch."""
        self._pending_path = None
        self._show(path)
        self._prepare_active_clip()

    def _prepare_active_clip(self) -> None:
        self.renderer.prepare_active_clip_for_current_size()
