from __future__ import annotations

from pathlib import Path

from genau.clip_runtime import ClipCacheStore
from genau.clip_selection import ClipSelectionController
from genau.clip_sequence import ClipSequenceController


class FakeLoader:
    def __init__(self, clip_store: ClipCacheStore, *, is_busy: bool = False, adopt_on_load: bool = False):
        self.clip_store = clip_store
        self.is_busy = is_busy
        self.adopt_on_load = adopt_on_load
        self.load_requests: list[Path] = []
        self.prefetch_requests: list[Path] = []

    def request_clip_load(self, path: Path) -> None:
        self.load_requests.append(path)
        if self.adopt_on_load:
            self.clip_store.clip_cache[path] = {"frames": ["f0"]}

    def request_prefetch(self, path: Path) -> None:
        self.prefetch_requests.append(path)


class FakeRenderer:
    def __init__(self):
        self.current_clip_path: Path | None = None
        self.prepare_calls = 0

    def set_current_clip_path(self, path: Path) -> None:
        self.current_clip_path = path

    def prepare_active_clip_for_current_size(self) -> None:
        self.prepare_calls += 1


class FakeNotifier:
    def __init__(self):
        self.clip_notifications: list[Path] = []

    def notify_clip(self, path: Path) -> None:
        self.clip_notifications.append(path)


def _build_controller(
    *paths: str, loader_busy: bool = False, adopt_on_load: bool = False, discard_clip=None,
):
    clip_store = ClipCacheStore(limit=3)
    sequence = ClipSequenceController([Path(path) for path in paths])
    loader = FakeLoader(clip_store, is_busy=loader_busy, adopt_on_load=adopt_on_load)
    renderer = FakeRenderer()
    notifier = FakeNotifier()

    kwargs = {} if discard_clip is None else {"discard_clip": discard_clip}
    controller = ClipSelectionController(
        sequence=sequence,
        clip_store=clip_store,
        loader=loader,
        renderer=renderer,
        notifier=notifier,
        **kwargs,
    )
    return controller, clip_store, loader, renderer, notifier


def test_set_current_clip_uses_cached_entry_without_loading():
    controller, clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    path = Path("b.mp4")
    clip_store.clip_cache[path] = {"frames": ["f0"]}

    controller.set_current_clip(path)

    assert renderer.current_clip_path == path
    assert renderer.prepare_calls == 1
    assert notifier.clip_notifications == [path]
    assert loader.load_requests == []


def test_set_current_clip_requests_load_for_uncached_entry():
    controller, _clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    path = Path("b.mp4")

    controller.set_current_clip(path)

    assert renderer.current_clip_path == path
    assert renderer.prepare_calls == 0
    assert notifier.clip_notifications == [path]
    assert loader.load_requests == [path]


def test_set_current_clip_prepares_when_load_adopts_immediately():
    controller, _clip_store, loader, renderer, notifier = _build_controller(
        "a.mp4",
        "b.mp4",
        adopt_on_load=True,
    )
    path = Path("b.mp4")

    controller.set_current_clip(path)

    assert renderer.current_clip_path == path
    assert renderer.prepare_calls == 1
    assert notifier.clip_notifications == [path]
    assert loader.load_requests == [path]


def test_step_switches_immediately_when_cached():
    controller, clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    clip_store.clip_cache[Path("b.mp4")] = {"frames": ["f0"]}

    controller.step(1)

    assert controller.current_number == 2
    assert renderer.current_clip_path == Path("b.mp4")
    assert notifier.clip_notifications == [Path("b.mp4")]
    assert renderer.prepare_calls == 1
    assert controller.pending_clip_name is None


def test_step_defers_switch_when_not_cached():
    controller, _clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    # Set initial clip on renderer
    renderer.current_clip_path = Path("a.mp4")

    controller.step(1)

    assert controller.current_number == 2
    # Renderer still shows old clip
    assert renderer.current_clip_path == Path("a.mp4")
    # No notification yet — deferred
    assert notifier.clip_notifications == []
    # Load was requested
    assert loader.load_requests == [Path("b.mp4")]
    # Pending clip name is set
    assert controller.pending_clip_name == "b.mp4"


def test_adopt_pending_clip_switches_when_loaded():
    controller, clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    renderer.current_clip_path = Path("a.mp4")

    controller.step(1)  # defers — b.mp4 not cached

    # Simulate async load completing
    clip_store.clip_cache[Path("b.mp4")] = {"frames": ["f0"]}
    result = controller.adopt_pending_clip()

    assert result is True
    assert renderer.current_clip_path == Path("b.mp4")
    assert notifier.clip_notifications == [Path("b.mp4")]
    assert renderer.prepare_calls == 1
    assert controller.pending_clip_name is None


def test_adopt_pending_clip_returns_false_when_not_ready():
    controller, _clip_store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
    renderer.current_clip_path = Path("a.mp4")

    controller.step(1)  # defers

    result = controller.adopt_pending_clip()

    assert result is False
    assert renderer.current_clip_path == Path("a.mp4")
    assert controller.pending_clip_name == "b.mp4"


def test_adopt_pending_clip_noop_when_no_pending():
    controller, _clip_store, _loader, _renderer, _notifier = _build_controller("a.mp4", "b.mp4")

    result = controller.adopt_pending_clip()

    assert result is False


def test_request_nearby_prefetch_uses_first_uncached_neighbor():
    controller, clip_store, loader, _renderer, _notifier = _build_controller(
        "a.mp4",
        "b.mp4",
        "c.mp4",
    )
    clip_store.clip_cache[Path("b.mp4")] = {"frames": ["f0"]}

    controller.request_nearby_prefetch()

    assert loader.prefetch_requests == [Path("c.mp4")]


def test_request_nearby_prefetch_skips_when_busy():
    controller, _clip_store, loader, _renderer, _notifier = _build_controller(
        "a.mp4",
        "b.mp4",
        loader_busy=True,
    )

    controller.request_nearby_prefetch()

    assert loader.prefetch_requests == []


def test_request_nearby_prefetch_is_empty_for_single_clip():
    controller, _clip_store, loader, _renderer, _notifier = _build_controller("solo.mp4")

    controller.request_nearby_prefetch()

    assert loader.prefetch_requests == []


class TestReorder:
    def test_takes_the_head_of_the_new_order_at_once(self):
        """Never deferred the way a step is: the point of asking for an order is
        to be shown what it puts first, so the head takes the screen and decodes
        there rather than behind the clip that was up."""
        controller, _store, loader, renderer, notifier = _build_controller("a.mp4", "b.mp4")
        renderer.current_clip_path = Path("a.mp4")

        controller.reorder([Path("newest.mp4"), Path("older.mp4")])

        assert renderer.current_clip_path == Path("newest.mp4")
        assert notifier.clip_notifications == [Path("newest.mp4")]
        assert loader.load_requests == [Path("newest.mp4")]
        assert controller.pending_clip_name is None
        assert controller.count == 2

    def test_drops_a_switch_that_was_still_waiting_to_load(self):
        """The deferred clip belongs to the order just replaced, so adopting it
        afterwards would put the old browse back on screen."""
        controller, clip_store, _loader, renderer, _notifier = _build_controller("a.mp4", "b.mp4")
        renderer.current_clip_path = Path("a.mp4")
        controller.step(1)
        assert controller.pending_clip_name == "b.mp4"

        controller.reorder([Path("newest.mp4")])
        clip_store.clip_cache[Path("b.mp4")] = {"frames": ["f0"]}

        assert controller.adopt_pending_clip() is False
        assert renderer.current_clip_path == Path("newest.mp4")


class TestDiscardCurrent:
    def test_condemns_the_clip_and_moves_on_to_the_next(self):
        condemned: list[Path] = []
        controller, clip_store, _loader, renderer, notifier = _build_controller(
            "a.mp4", "b.mp4", "c.mp4", discard_clip=condemned.append,
        )
        clip_store.clip_cache[Path("b.mp4")] = {"frames": ["f0"]}

        assert controller.discard_current() is True

        assert condemned == [Path("a.mp4")]
        assert controller.count == 2
        assert renderer.current_clip_path == Path("b.mp4")
        assert notifier.clip_notifications == [Path("b.mp4")]

    def test_the_only_clip_is_never_condemned(self):
        """Genau always has something on screen, so the last clip is untouchable."""
        condemned: list[Path] = []
        controller, _store, _loader, renderer, _notifier = _build_controller(
            "a.mp4", discard_clip=condemned.append,
        )

        assert controller.discard_current() is False

        assert condemned == []
        assert controller.count == 1
        assert renderer.current_clip_path is None
