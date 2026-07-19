"""Tests for genau_vr.vr_session frame pacing."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import xr

from genau_vr.vr_session import VRSession

BOTH_VALID = xr.ViewStateFlags.ORIENTATION_VALID_BIT | xr.ViewStateFlags.POSITION_VALID_BIT


def _idle_session() -> VRSession:
    """A VRSession far enough along to answer frame_begin, without any real VR."""
    session = VRSession.__new__(VRSession)
    session._session = object()
    session._space = object()
    session._session_state = xr.SessionState.VISIBLE
    return session


def _xr_stub(*, view_flags: int, views: list) -> MagicMock:
    stub = MagicMock()
    stub.SessionState = xr.SessionState
    stub.ViewStateFlags = xr.ViewStateFlags
    stub.wait_frame.return_value = SimpleNamespace(
        should_render=True, predicted_display_time=4242,
    )
    stub.locate_views.return_value = (
        SimpleNamespace(view_state_flags=view_flags), views,
    )
    return stub


def test_frame_begin_passes_views_on_once_the_runtime_says_they_are_valid():
    views = [object(), object()]
    with patch("genau_vr.vr_session.xr", _xr_stub(view_flags=BOTH_VALID, views=views)):
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
    flags = xr.ViewStateFlags.ORIENTATION_VALID_BIT
    with patch("genau_vr.vr_session.xr", _xr_stub(view_flags=flags, views=[object()])):
        should_render, _, out = _idle_session().frame_begin()

    assert not should_render
    assert out == []
