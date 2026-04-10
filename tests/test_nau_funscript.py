from __future__ import annotations

import json

from nau.funscript import Funscript, load, snap_loop


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


class TestSnapLoop:
    def _make_fs(self):
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

        assert result[1] - result[0] >= 500
