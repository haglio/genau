"""Tests for genau_vr.vr_session frame pacing."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from genau_vr.vr_session import VRSession


def _xr():
    """The real loader, asked for by the cases that need its own enums.

    Not imported at module scope: doing that made all three cases here a
    collection error on a machine without the loader, and a collection error is
    a file dropped from the run rather than a test that failed.
    """
    import xr  # noqa: PLC0415 — only the cases that need the loader should load it

    return xr


def _both_valid() -> int:
    flags = _xr().ViewStateFlags
    return flags.ORIENTATION_VALID_BIT | flags.POSITION_VALID_BIT


def _idle_session() -> VRSession:
    """A VRSession far enough along to answer frame_begin, without any real VR."""
    session = VRSession.__new__(VRSession)
    session._session = object()
    session._space = object()
    session._session_state = _xr().SessionState.VISIBLE
    return session


def _xr_stub(*, view_flags: int, views: list) -> MagicMock:
    stub = MagicMock()
    stub.SessionState = _xr().SessionState
    stub.ViewStateFlags = _xr().ViewStateFlags
    stub.wait_frame.return_value = SimpleNamespace(
        should_render=True, predicted_display_time=4242,
    )
    stub.locate_views.return_value = (
        SimpleNamespace(view_state_flags=view_flags), views,
    )
    return stub


def test_frame_begin_passes_views_on_once_the_runtime_says_they_are_valid():
    views = [object(), object()]
    with patch("genau_vr.vr_session.xr", _xr_stub(view_flags=_both_valid(), views=views)):
        should_render, display_time, out = _idle_session().frame_begin()

    assert should_render
    assert out == views
    assert display_time == 4242


def test_frame_begin_withholds_views_the_runtime_has_not_located_yet():
    """A view with no valid pose carries a zeroed FOV, which divides by zero downstream.

    The runtime returns exactly that for the first frames after the session turns
    visible, before tracking is established.
    """
    with patch("genau_vr.vr_session.xr", _xr_stub(view_flags=0, views=[object(), object()])):
        should_render, _, out = _idle_session().frame_begin()

    assert not should_render
    assert out == []


def test_frame_begin_withholds_views_with_only_an_orientation():
    flags = _xr().ViewStateFlags.ORIENTATION_VALID_BIT
    with patch("genau_vr.vr_session.xr", _xr_stub(view_flags=flags, views=[object()])):
        should_render, _, out = _idle_session().frame_begin()

    assert not should_render
    assert out == []
