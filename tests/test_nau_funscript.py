from __future__ import annotations

import json

import pytest

from nau.funscript import Funscript, interpolate, load, snap_loop


class TestLoad:
    def test_parses_actions(self, tmp_path):
        data = {
            "actions": [
                {"at": 1000, "pos": 0},
                {"at": 2000, "pos": 100},
                {"at": 500, "pos": 50},
            ]
        }
        path = tmp_path / "test.funscript"
        path.write_text(json.dumps(data))

        fs = load(path)

        assert fs.actions == [(500, 50), (1000, 0), (2000, 100)]


class TestInterpolate:
    def test_exact_timestamp(self):
        fs = Funscript(actions=[(0, 0), (1000, 50), (2000, 100)])

        assert interpolate(fs, 1000) == 50.0

    def test_between_actions(self):
        fs = Funscript(actions=[(0, 0), (1000, 100)])

        assert interpolate(fs, 500) == pytest.approx(50.0)

    def test_before_first_action(self):
        fs = Funscript(actions=[(1000, 80), (2000, 100)])

        assert interpolate(fs, 0) == 80.0

    def test_after_last_action(self):
        fs = Funscript(actions=[(0, 0), (1000, 40)])

        assert interpolate(fs, 5000) == 40.0


class TestSnapLoop:
    def _make_fs(self):
        # Strokes: base at 0, 2000, 4000, 6000ms (pos=100)
        # Midpoints at 1000, 3000, 5000ms (pos=0)
        return Funscript(actions=[
            (0, 100), (1000, 0), (2000, 100), (3000, 0),
            (4000, 100), (5000, 0), (6000, 100),
        ])

    def test_snaps_outward_to_base_positions(self):
        fs = self._make_fs()

        result = snap_loop(fs, 2500, 3500)

        assert result == (2000, 4000)

    def test_in_already_on_base(self):
        fs = self._make_fs()

        result = snap_loop(fs, 2000, 3500)

        assert result == (2000, 4000)

    def test_no_base_before_in(self):
        fs = Funscript(actions=[
            (1000, 0), (2000, 100), (3000, 0), (4000, 100),
        ])

        result = snap_loop(fs, 500, 2500)

        assert result == (1000, 4000)

    def test_no_base_after_out(self):
        fs = Funscript(actions=[
            (0, 100), (1000, 0), (2000, 100), (3000, 0),
        ])

        result = snap_loop(fs, 2500, 3500)

        assert result == (2000, 3000)

    def test_zero_duration_extends(self):
        fs = self._make_fs()

        result = snap_loop(fs, 2050, 2050)

        # Should extend: In snaps to 2000, Out snaps to 4000
        assert result[1] - result[0] >= 500
