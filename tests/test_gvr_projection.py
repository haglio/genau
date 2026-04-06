from __future__ import annotations

import math

import pytest

import numpy as np

from genau_vr.projection import (
    direction_to_equirect_uv,
    equirect_uv_to_sbs_vr180,
    fov_to_projection_matrix,
    pose_to_view_matrix,
)


class TestDirectionToEquirectUv:
    def test_forward_maps_to_center(self):
        u, v = direction_to_equirect_uv(0.0, 0.0, -1.0)
        assert u == pytest.approx(0.5)
        assert v == pytest.approx(0.5)

    def test_left_maps_to_left_edge(self):
        u, v = direction_to_equirect_uv(-1.0, 0.0, 0.0)
        assert u == pytest.approx(0.25)
        assert v == pytest.approx(0.5)

    def test_right_maps_to_right_edge(self):
        u, v = direction_to_equirect_uv(1.0, 0.0, 0.0)
        assert u == pytest.approx(0.75)
        assert v == pytest.approx(0.5)

    def test_up_maps_to_top(self):
        u, v = direction_to_equirect_uv(0.0, 1.0, 0.0)
        assert v == pytest.approx(0.0)

    def test_down_maps_to_bottom(self):
        u, v = direction_to_equirect_uv(0.0, -1.0, 0.0)
        assert v == pytest.approx(1.0)

    def test_backward_maps_to_edge(self):
        u, v = direction_to_equirect_uv(0.0, 0.0, 1.0)
        assert (u == pytest.approx(0.0) or u == pytest.approx(1.0))
        assert v == pytest.approx(0.5)

    def test_unnormalized_direction_works(self):
        u, v = direction_to_equirect_uv(0.0, 0.0, -5.0)
        assert u == pytest.approx(0.5)
        assert v == pytest.approx(0.5)


class TestEquirectUvToSbsVr180:
    def test_left_eye_center_maps_to_quarter(self):
        u_sbs, v_sbs = equirect_uv_to_sbs_vr180(0.5, 0.5, eye=0)
        assert u_sbs == pytest.approx(0.25)
        assert v_sbs == pytest.approx(0.5)

    def test_right_eye_center_maps_to_three_quarters(self):
        u_sbs, v_sbs = equirect_uv_to_sbs_vr180(0.5, 0.5, eye=1)
        assert u_sbs == pytest.approx(0.75)
        assert v_sbs == pytest.approx(0.5)

    def test_left_eye_range_is_zero_to_half(self):
        u_lo, _ = equirect_uv_to_sbs_vr180(0.0, 0.0, eye=0)
        u_hi, _ = equirect_uv_to_sbs_vr180(1.0, 0.0, eye=0)
        assert u_lo == pytest.approx(0.0)
        assert u_hi == pytest.approx(0.5)

    def test_right_eye_range_is_half_to_one(self):
        u_lo, _ = equirect_uv_to_sbs_vr180(0.0, 0.0, eye=1)
        u_hi, _ = equirect_uv_to_sbs_vr180(1.0, 0.0, eye=1)
        assert u_lo == pytest.approx(0.5)
        assert u_hi == pytest.approx(1.0)

    def test_v_coordinate_passes_through(self):
        _, v = equirect_uv_to_sbs_vr180(0.3, 0.7, eye=0)
        assert v == pytest.approx(0.7)


class TestFovToProjectionMatrix:
    def test_symmetric_fov_shape(self):
        # 90-degree symmetric FOV
        half = math.radians(45)
        mat = fov_to_projection_matrix(-half, half, half, -half, 0.1, 100.0)
        assert mat.shape == (4, 4)

    def test_symmetric_fov_produces_symmetric_matrix(self):
        half = math.radians(45)
        mat = fov_to_projection_matrix(-half, half, half, -half, 0.1, 100.0)
        # For symmetric FOV: m[0,2] and m[1,2] should be 0 (no off-center shift)
        assert mat[0, 2] == pytest.approx(0.0)
        assert mat[1, 2] == pytest.approx(0.0)

    def test_near_far_encoded_in_matrix(self):
        half = math.radians(45)
        mat = fov_to_projection_matrix(-half, half, half, -half, 0.1, 100.0)
        # m[3,2] should be -1 (perspective divide)
        assert mat[3, 2] == pytest.approx(-1.0)
        # m[2,3] should encode near*far product
        assert mat[2, 3] == pytest.approx(-2.0 * 100.0 * 0.1 / (100.0 - 0.1))


class TestPoseToViewMatrix:
    def test_identity_pose_returns_identity(self):
        pos = (0.0, 0.0, 0.0)
        quat = (0.0, 0.0, 0.0, 1.0)  # (x, y, z, w) identity
        mat = pose_to_view_matrix(pos, quat)
        assert mat.shape == (4, 4)
        np.testing.assert_allclose(mat, np.eye(4), atol=1e-7)

    def test_translation_only(self):
        pos = (1.0, 2.0, 3.0)
        quat = (0.0, 0.0, 0.0, 1.0)
        mat = pose_to_view_matrix(pos, quat)
        # View matrix inverts the pose, so translation should be negated
        assert mat[0, 3] == pytest.approx(-1.0)
        assert mat[1, 3] == pytest.approx(-2.0)
        assert mat[2, 3] == pytest.approx(-3.0)
