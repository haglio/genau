"""OpenGL rendering for VR180 SBS equirectangular video on a hemisphere."""
from __future__ import annotations

import ctypes
import logging

import numpy as np
from OpenGL import GL

logger = logging.getLogger(__name__)

VERTEX_SHADER = """
#version 330 core
out vec2 screen_pos;
void main() {
    // Full-screen triangle (3 vertices cover the screen, more efficient than a quad)
    vec2 positions[3] = vec2[](
        vec2(-1.0, -1.0),
        vec2( 3.0, -1.0),
        vec2(-1.0,  3.0)
    );
    gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
    screen_pos = positions[gl_VertexID];
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec2 screen_pos;
out vec4 frag_color;

uniform sampler2D video_tex;
uniform mat4 inv_view_proj;
uniform int eye;  // 0=left, 1=right

const float PI = 3.14159265359;

void main() {
    // Reconstruct world-space ray direction from screen position
    vec4 clip_pos = vec4(screen_pos, -1.0, 1.0);
    vec4 world_dir = inv_view_proj * clip_pos;
    vec3 dir = normalize(world_dir.xyz);

    // Spherical coordinates (OpenGL: +X right, +Y up, -Z forward)
    float theta = atan(dir.x, -dir.z);        // longitude [-pi, pi]
    float phi = asin(clamp(dir.y, -1.0, 1.0)); // latitude [-pi/2, pi/2]

    // VR180: discard directions behind the viewer
    if (abs(theta) > PI * 0.5) {
        frag_color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // Map to equirectangular UV over 180 degrees
    float u = (theta / PI) * 0.5 + 0.5;  // [0, 1] over front hemisphere
    float v = (-phi / PI) + 0.5;          // [0, 1] top to bottom

    // Side-by-side layout: left eye uses left half, right eye uses right half
    float u_sbs = u * 0.5 + float(eye) * 0.5;

    frag_color = texture(video_tex, vec2(u_sbs, v));
}
"""


class VRRenderer:
    """Handles shader compilation, video texture upload, and per-eye rendering."""

    def __init__(self) -> None:
        self._program = _compile_program(VERTEX_SHADER, FRAGMENT_SHADER)
        self._vao = GL.glGenVertexArrays(1)
        self._texture = _create_video_texture()
        self._loc_inv_vp = GL.glGetUniformLocation(self._program, "inv_view_proj")
        self._loc_eye = GL.glGetUniformLocation(self._program, "eye")
        self._loc_tex = GL.glGetUniformLocation(self._program, "video_tex")
        self._render_count = 0
        logger.info(
            "Renderer init: program=%d, vao=%d, tex=%d, locs=(%d,%d,%d)",
            self._program, self._vao, self._texture,
            self._loc_inv_vp, self._loc_eye, self._loc_tex,
        )

    def upload_frame(self, frame: np.ndarray) -> None:
        """Upload a numpy RGB frame to the video texture."""
        h, w = frame.shape[:2]
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8,
            w, h, 0,
            GL.GL_RGB, GL.GL_UNSIGNED_BYTE,
            frame,
        )
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def render_eye(self, eye_index: int, inv_view_proj: np.ndarray) -> None:
        """Render the VR180 hemisphere for one eye.

        Assumes the target framebuffer is already bound.
        """
        self._render_count += 1

        GL.glClearColor(0.2, 0.0, 0.2, 1.0)  # Dark purple so we can distinguish from "nothing rendered"
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        GL.glUseProgram(self._program)
        GL.glUniform1i(self._loc_eye, eye_index)
        GL.glUniform1i(self._loc_tex, 0)
        GL.glUniformMatrix4fv(self._loc_inv_vp, 1, GL.GL_TRUE, inv_view_proj.astype(np.float32))

        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)

        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)

        GL.glUseProgram(0)

        if self._render_count <= 4:
            err = GL.glGetError()
            fbo_status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
            pixel = GL.glReadPixels(10, 10, 1, 1, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
            pixel_bytes = bytes(pixel) if pixel is not None else b""
            logger.info(
                "render_eye(%d): gl_error=%d, fbo=%d(ok=%d), pixel=%s",
                eye_index, err, fbo_status, GL.GL_FRAMEBUFFER_COMPLETE,
                pixel_bytes[:4].hex() if pixel_bytes else "none",
            )

    def close(self) -> None:
        GL.glDeleteProgram(self._program)
        GL.glDeleteVertexArrays(1, [self._vao])
        GL.glDeleteTextures(1, [self._texture])


def _compile_shader(source: str, shader_type: int) -> int:
    shader = GL.glCreateShader(shader_type)
    GL.glShaderSource(shader, source)
    GL.glCompileShader(shader)
    if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(shader).decode()
        GL.glDeleteShader(shader)
        raise RuntimeError(f"Shader compilation failed:\n{log}")
    return shader


def _compile_program(vert_src: str, frag_src: str) -> int:
    vert = _compile_shader(vert_src, GL.GL_VERTEX_SHADER)
    frag = _compile_shader(frag_src, GL.GL_FRAGMENT_SHADER)
    program = GL.glCreateProgram()
    GL.glAttachShader(program, vert)
    GL.glAttachShader(program, frag)
    GL.glLinkProgram(program)
    if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(program).decode()
        GL.glDeleteProgram(program)
        raise RuntimeError(f"Program link failed:\n{log}")
    GL.glDeleteShader(vert)
    GL.glDeleteShader(frag)
    return program


def _create_video_texture() -> int:
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    # Upload a 1x1 black pixel as placeholder
    GL.glTexImage2D(
        GL.GL_TEXTURE_2D, 0, GL.GL_SRGB8_ALPHA8,
        1, 1, 0,
        GL.GL_RGB, GL.GL_UNSIGNED_BYTE,
        np.zeros((1, 1, 3), dtype=np.uint8),
    )
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return tex
