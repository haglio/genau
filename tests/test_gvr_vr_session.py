"""Tests for genau_vr.vr_session frame pacing and controller input."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from genau.tick_failures import TickFailures
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


class TestWhenTheControllerStopsAnswering:
    """It used to be discarded outright: the thumbstick stopped working, the
    picture stopped tilting, and the log said nothing for the whole session.

    Driven with a stand-in loader, so these run on a machine with no OpenXR.
    """

    @staticmethod
    def _session(stub) -> VRSession:
        session = VRSession.__new__(VRSession)
        session._session = object()
        session._action_set = object()
        session._thumbstick_y_action = object()
        session._actions_attached = True
        session.thumbstick_y = 0.0
        session._controller_failures = TickFailures(
            logging.getLogger("test.vr_session"), what="controller sync")
        return session

    @staticmethod
    def _refusing_loader() -> MagicMock:
        stub = MagicMock()
        stub.ResultException = _AnswerRefused
        stub.sync_actions.side_effect = _AnswerRefused("the runtime would not answer")
        return stub

    def test_a_runtime_that_refuses_leaves_the_thumbstick_where_it_was(self):
        stub = self._refusing_loader()
        session = self._session(stub)
        session.thumbstick_y = 0.4

        with patch("genau_vr.vr_session.xr", stub):
            session.sync_controller()

        assert session.thumbstick_y == 0.4

    def test_it_says_so_once_with_the_reason(self, caplog):
        stub = self._refusing_loader()
        session = self._session(stub)

        with patch("genau_vr.vr_session.xr", stub), \
                caplog.at_level(logging.DEBUG, logger="test.vr_session"):
            for _ in range(60):
                session.sync_controller()

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1
        assert "controller sync" in errors[0].getMessage()

    def test_a_controller_that_comes_back_says_how_many_were_swallowed(self, caplog):
        stub = self._refusing_loader()
        session = self._session(stub)

        with patch("genau_vr.vr_session.xr", stub), \
                caplog.at_level(logging.DEBUG, logger="test.vr_session"):
            for _ in range(5):
                session.sync_controller()
            stub.sync_actions.side_effect = None
            stub.get_action_state_float.return_value = SimpleNamespace(
                is_active=True, current_state=0.6)
            session.sync_controller()

        assert session.thumbstick_y == 0.6
        assert any("4" in r.getMessage() for r in caplog.records)

    def test_a_controller_reporting_nothing_reads_as_centered(self):
        """Not as "leave it where it was": a stick let go of has to stop the
        picture turning."""
        stub = MagicMock()
        stub.ResultException = _AnswerRefused
        stub.get_action_state_float.return_value = SimpleNamespace(
            is_active=False, current_state=0.9)
        session = self._session(stub)
        session.thumbstick_y = 0.4

        with patch("genau_vr.vr_session.xr", stub):
            session.sync_controller()

        assert session.thumbstick_y == 0.0

    def test_a_session_with_no_action_set_asks_nothing(self):
        stub = MagicMock()
        session = self._session(stub)
        session._actions_attached = False

        with patch("genau_vr.vr_session.xr", stub):
            session.sync_controller()

        assert stub.sync_actions.call_count == 0


class _AnswerRefused(Exception):
    """Standing in for xr.ResultException, which needs the loader to exist."""
