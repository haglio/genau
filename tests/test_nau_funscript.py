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


class TestFirstRealEventMs:
    def test_dense_from_start_has_no_lead_in(self):
        fs = Funscript(actions=[(0, 0), (300, 100), (600, 0), (900, 100)])

        assert fs.first_real_event_ms is None

    def test_action_starting_late_reports_onset(self):
        fs = Funscript(actions=[(60000, 0), (60300, 100), (60600, 0)])

        assert fs.first_real_event_ms == 60000

    def test_isolated_leading_blip_is_skipped(self):
        # A stray blip at t=0, a long quiet gap, then dense action at 34s.
        fs = Funscript(actions=[
            (0, 50), (34000, 0), (34300, 100), (34600, 0), (34900, 100),
        ])

        assert fs.first_real_event_ms == 34000

    def test_sparse_throughout_has_no_onset(self):
        # Every action is isolated (10s apart): there is no dense onset to
        # rest up to, so drive normally rather than park the whole video.
        fs = Funscript(actions=[(0, 0), (10000, 100), (20000, 0), (30000, 100)])

        assert fs.first_real_event_ms is None

    def test_short_lead_in_is_not_worth_parking(self):
        # Dense action begins at 4s — under the "a long time" threshold, so no
        # parking (a momentary rest at the very start is not worth it).
        fs = Funscript(actions=[(4000, 0), (4300, 100), (4600, 0), (4900, 100)])

        assert fs.first_real_event_ms is None


class TestIsRestingAt:
    def test_on_a_dense_cluster_is_not_resting(self):
        fs = Funscript(actions=[(10000, 0), (10300, 100), (10600, 0), (10900, 100)])

        assert fs.is_resting_at(10300) is False

    def test_deep_gap_between_clusters_is_resting(self):
        fs = Funscript(actions=[
            (10000, 0), (10300, 100), (10600, 0),   # cluster A
            (40000, 0), (40300, 100), (40600, 0),   # cluster B
        ])

        assert fs.is_resting_at(25000) is True  # midway in the 30s gap

    def test_buffer_before_a_cluster_is_not_resting(self):
        # The funscript reclaims a _QUIET_LEAD_IN_MS buffer ahead of its action,
        # so the OSR2 settles onto the script before it fires.
        fs = Funscript(actions=[(40000, 0), (40300, 100), (40600, 0)])

        assert fs.is_resting_at(37000) is False  # 3s before -> inside the buffer
        assert fs.is_resting_at(34000) is True   # 6s before -> still the gap

    def test_quiet_lead_in_is_resting(self):
        fs = Funscript(actions=[(60000, 0), (60300, 100), (60600, 0)])

        assert fs.is_resting_at(0) is True

    def test_isolated_blip_does_not_anchor_driving(self):
        # A stray blip with no dense neighbour must not pull the OSR2 off Genau.
        fs = Funscript(actions=[(20000, 50), (60000, 0), (60300, 100), (60600, 0)])

        assert fs.is_resting_at(20000) is True

    def test_sparse_funscript_is_all_resting(self):
        # Every action isolated (10s apart): no dense scripting, Genau drives.
        fs = Funscript(actions=[(0, 0), (10000, 100), (20000, 0), (30000, 100)])

        assert fs.is_resting_at(15000) is True


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
