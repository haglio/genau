from __future__ import annotations

import math

import pytest

import numpy as np

from genau_vr import projection
from genau_vr.projection import (
    fov_to_projection_matrix,
    pitch_rotation_matrix,
    pose_to_view_matrix,
)


def test_the_module_holds_no_second_model_of_the_projection():
    """The equirect mapping lives in the fragment shader and only there.

    Two Python helpers used to model it and disagreed with it: 360 degrees
    against the shader's 180, and for a direction behind the viewer they
    returned a texture coordinate where the shader draws black. Nothing
    called them, so twelve tests reported green on a projection the product
    does not use.
    """
    own = {
        name for name, value in vars(projection).items()
        if not name.startswith("_") and callable(value)
        and getattr(value, "__module__", "") == projection.__name__
    }

    assert own == {"fov_to_projection_matrix", "pose_to_view_matrix",
                   # The tilt the thumbstick applies, moved here from the app
                   # module to sit beside the two matrices it is folded into.
                   "pitch_rotation_matrix"}


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


class TestTiltingTheView:
    """The controller's pitch adjustment, as a rotation about the X axis."""

    def test_a_quarter_turn_takes_up_onto_the_axis_pointing_away(self):
        """Up is +Y and away is -Z in this space, so a positive quarter turn
        tips the view down toward the floor.  Flip the sign and the controller
        pitches the other way."""
        turned = pitch_rotation_matrix(math.pi / 2) @ np.array(
            [0.0, 1.0, 0.0, 1.0], dtype=np.float32)

        assert turned[:3] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)

    def test_no_turn_leaves_every_axis_where_it_was(self):
        assert pitch_rotation_matrix(0.0) == pytest.approx(np.eye(4))

    def test_it_only_touches_the_two_axes_it_turns_between(self):
        """X is the axis being turned about and W carries the translation, so a
        rotation that moved either would drag the whole scene with it."""
        turned = pitch_rotation_matrix(math.pi / 3)

        assert turned[0] == pytest.approx([1.0, 0.0, 0.0, 0.0])
        assert turned[3] == pytest.approx([0.0, 0.0, 0.0, 1.0])
