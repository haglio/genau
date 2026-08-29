from __future__ import annotations

import math

import numpy as np


def fov_to_projection_matrix(
    angle_left: float,
    angle_right: float,
    angle_up: float,
    angle_down: float,
    near: float,
    far: float,
) -> np.ndarray:
    """Build an OpenGL projection matrix from OpenXR FOV angles (radians).

    Returns a 4x4 column-major-compatible matrix (row-major numpy layout
    that matches OpenGL when transposed, but we use row-vector convention
    consistent with numpy @ vec).
    """
    tan_l = math.tan(angle_left)
    tan_r = math.tan(angle_right)
    tan_u = math.tan(angle_up)
    tan_d = math.tan(angle_down)

    width = tan_r - tan_l
    height = tan_u - tan_d

    mat = np.zeros((4, 4), dtype=np.float32)
    mat[0, 0] = 2.0 / width
    mat[0, 2] = (tan_r + tan_l) / width
    mat[1, 1] = 2.0 / height
    mat[1, 2] = (tan_u + tan_d) / height
    mat[2, 2] = -(far + near) / (far - near)
    mat[2, 3] = -(2.0 * far * near) / (far - near)
    mat[3, 2] = -1.0
    return mat


def _quat_to_rotation_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """Convert quaternion (x, y, z, w) to a 3x3 rotation matrix."""
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array([
        [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
        [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
        [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
    ], dtype=np.float32)


def pose_to_view_matrix(
    position: tuple[float, float, float],
    orientation: tuple[float, float, float, float],
) -> np.ndarray:
    """Build a view matrix from an OpenXR pose.

    position: (x, y, z)
    orientation: quaternion (x, y, z, w)
    Returns: 4x4 view matrix (inverse of the pose transform).
    """
    rot = _quat_to_rotation_matrix(*orientation)
    pos = np.array(position, dtype=np.float32)

    mat = np.eye(4, dtype=np.float32)
    mat[:3, :3] = rot.T
    mat[:3, 3] = -rot.T @ pos
    return mat
