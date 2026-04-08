"""OpenXR session lifecycle, swapchain management, and controller input."""
from __future__ import annotations

import ctypes
import logging
import platform
from dataclasses import dataclass, field
from pathlib import Path

import glfw
import xr
from OpenGL import GL

logger = logging.getLogger(__name__)


@dataclass
class SwapchainInfo:
    handle: xr.Swapchain
    width: int
    height: int
    images: list[int] = field(default_factory=list)


class VRSession:
    """Manages the OpenXR instance, session, reference space, swapchains, and input."""

    def __init__(self, *, app_name: str = "GenauVR") -> None:
        self.running = True
        self._window = None
        self._instance = None
        self._session = None
        self._space = None
        self._session_state = xr.SessionState.UNKNOWN
        self._session_begun = False
        self.swapchains: list[SwapchainInfo] = []
        self.view_config_views: list[xr.ViewConfigurationView] = []
        self._fbo = 0
        self._depth_buffers: list[int] = []
        # Controller
        self._action_set = None
        self._thumbstick_y_action = None
        self._actions_attached = False
        self.thumbstick_y: float = 0.0

        self._init_glfw()
        self._init_openxr(app_name)
        self._init_actions()
        self._create_swapchains()
        self._create_framebuffer()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_glfw(self) -> None:
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 5)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.DECORATED, glfw.TRUE)
        self._window = glfw.create_window(300, 200, "GenauVR", None, None)
        if not self._window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")
        glfw.make_context_current(self._window)
        self._set_window_icon()

    def _set_window_icon(self) -> None:
        ico_path = Path(__file__).resolve().parent.parent / "genau_vr_icon.ico"
        try:
            from PIL import Image
            img = Image.open(str(ico_path)).resize((32, 32)).convert("RGBA")
            glfw.set_window_icon(self._window, 1, [img])
        except Exception:
            logger.debug("Could not set window icon", exc_info=True)

    def _init_openxr(self, app_name: str) -> None:
        extensions = [xr.KHR_OPENGL_ENABLE_EXTENSION_NAME]
        self._instance = xr.create_instance(
            xr.InstanceCreateInfo(
                application_info=xr.ApplicationInfo(app_name, 0, "", 0, xr.Version(1, 0, 0)),
                enabled_extension_names=extensions,
            )
        )

        system_id = xr.get_system(
            self._instance,
            xr.SystemGetInfo(form_factor=xr.FormFactor.HEAD_MOUNTED_DISPLAY),
        )

        self.view_config_views = xr.enumerate_view_configuration_views(
            self._instance, system_id, xr.ViewConfigurationType.PRIMARY_STEREO,
        )

        xr.get_opengl_graphics_requirements_khr(self._instance, system_id)

        if platform.system() == "Windows":
            from OpenGL import WGL
            graphics_binding = xr.GraphicsBindingOpenGLWin32KHR(
                h_dc=WGL.wglGetCurrentDC(),
                h_glrc=WGL.wglGetCurrentContext(),
            )
        else:
            raise RuntimeError("Only Windows is supported for now")

        self._session = xr.create_session(
            self._instance,
            xr.SessionCreateInfo(
                system_id=system_id,
                next=ctypes.cast(ctypes.pointer(graphics_binding), ctypes.c_void_p),
            ),
        )

        self._space = xr.create_reference_space(
            self._session,
            xr.ReferenceSpaceCreateInfo(
                reference_space_type=xr.ReferenceSpaceType.LOCAL,
                pose_in_reference_space=xr.Posef(
                    orientation=xr.Quaternionf(0, 0, 0, 1),
                    position=xr.Vector3f(0, 0, 0),
                ),
            ),
        )

    def _init_actions(self) -> None:
        """Create action set and actions for VR controller input."""
        try:
            self._action_set = xr.create_action_set(
                self._instance,
                xr.ActionSetCreateInfo(
                    action_set_name="genau_vr",
                    localized_action_set_name="GenauVR Controls",
                    priority=0,
                ),
            )

            self._thumbstick_y_action = xr.create_action(
                self._action_set,
                xr.ActionCreateInfo(
                    action_name="pitch_adjust",
                    action_type=xr.ActionType.FLOAT_INPUT,
                    localized_action_name="Pitch Adjust",
                ),
            )

            # Suggest bindings for common controller profiles
            for profile_path, stick_path in [
                ("/interaction_profiles/oculus/touch_controller", "/user/hand/right/input/thumbstick/y"),
                ("/interaction_profiles/valve/index_controller", "/user/hand/right/input/thumbstick/y"),
                ("/interaction_profiles/htc/vive_controller", "/user/hand/right/input/trackpad/y"),
            ]:
                try:
                    binding = xr.ActionSuggestedBinding(
                        action=self._thumbstick_y_action,
                        binding=xr.string_to_path(self._instance, stick_path),
                    )
                    xr.suggest_interaction_profile_bindings(
                        self._instance,
                        xr.InteractionProfileSuggestedBinding(
                            interaction_profile=xr.string_to_path(self._instance, profile_path),
                            suggested_bindings=[binding],
                        ),
                    )
                except xr.ResultException as exc:
                    logger.debug("Skipping profile %s: %s", profile_path, exc)

            xr.attach_session_action_sets(
                self._session,
                xr.SessionActionSetsAttachInfo(action_sets=[self._action_set]),
            )
            self._actions_attached = True
            logger.info("VR controller input initialized")
        except Exception:
            logger.warning("VR controller input unavailable", exc_info=True)

    def _create_swapchains(self) -> None:
        for view_cfg in self.view_config_views:
            w = view_cfg.recommended_image_rect_width
            h = view_cfg.recommended_image_rect_height

            sc = xr.create_swapchain(
                self._session,
                xr.SwapchainCreateInfo(
                    usage_flags=xr.SwapchainUsageFlags.COLOR_ATTACHMENT_BIT,
                    format=GL.GL_SRGB8_ALPHA8,
                    sample_count=1,
                    width=w,
                    height=h,
                    face_count=1,
                    array_size=1,
                    mip_count=1,
                ),
            )

            images = xr.enumerate_swapchain_images(sc, xr.SwapchainImageOpenGLKHR)
            sc_info = SwapchainInfo(
                handle=sc,
                width=w,
                height=h,
                images=[img.image for img in images],
            )
            logger.info("Swapchain %d: %dx%d, %d images", len(self.swapchains), w, h, len(sc_info.images))
            self.swapchains.append(sc_info)

    def _create_framebuffer(self) -> None:
        self._fbo = GL.glGenFramebuffers(1)
        for sc_info in self.swapchains:
            depth = GL.glGenRenderbuffers(1)
            GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, depth)
            GL.glRenderbufferStorage(GL.GL_RENDERBUFFER, GL.GL_DEPTH_COMPONENT24, sc_info.width, sc_info.height)
            self._depth_buffers.append(depth)
        GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, 0)

    # ------------------------------------------------------------------
    # Frame loop
    # ------------------------------------------------------------------

    def poll_events(self) -> None:
        while True:
            try:
                buf = xr.poll_event(self._instance)
            except xr.EventUnavailable:
                break

            if buf.type == xr.StructureType.EVENT_DATA_SESSION_STATE_CHANGED:
                event = ctypes.cast(
                    ctypes.byref(buf),
                    ctypes.POINTER(xr.EventDataSessionStateChanged),
                ).contents
                self._session_state = xr.SessionState(event.state)
                logger.info("Session state → %s", self._session_state.name)
                if self._session_state == xr.SessionState.READY:
                    xr.begin_session(
                        self._session,
                        xr.SessionBeginInfo(
                            primary_view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO,
                        ),
                    )
                    self._session_begun = True
                elif self._session_state == xr.SessionState.STOPPING:
                    xr.end_session(self._session)
                elif self._session_state in (
                    xr.SessionState.LOSS_PENDING,
                    xr.SessionState.EXITING,
                ):
                    self.running = False

    @property
    def session_ready(self) -> bool:
        return self._session_begun

    def sync_controller(self) -> None:
        """Sync controller actions and update thumbstick state."""
        if not self._actions_attached or self._action_set is None:
            return
        try:
            xr.sync_actions(
                self._session,
                xr.ActionsSyncInfo(
                    active_action_sets=[
                        xr.ActiveActionSet(action_set=self._action_set, subaction_path=0),
                    ],
                ),
            )
            state = xr.get_action_state_float(
                self._session,
                xr.ActionStateGetInfo(action=self._thumbstick_y_action, subaction_path=0),
            )
            if state.is_active:
                self.thumbstick_y = state.current_state
            else:
                self.thumbstick_y = 0.0
        except xr.ResultException:
            pass

    def frame_begin(self) -> tuple[bool, int, list[xr.View]]:
        frame_state = xr.wait_frame(self._session, xr.FrameWaitInfo())
        xr.begin_frame(self._session, xr.FrameBeginInfo())

        should_render = bool(frame_state.should_render) and self._session_state in (
            xr.SessionState.VISIBLE, xr.SessionState.FOCUSED,
        )

        views: list[xr.View] = []
        if should_render:
            view_state, views_raw = xr.locate_views(
                self._session,
                xr.ViewLocateInfo(
                    view_configuration_type=xr.ViewConfigurationType.PRIMARY_STEREO,
                    display_time=frame_state.predicted_display_time,
                    space=self._space,
                ),
            )
            views = list(views_raw)

        return should_render, frame_state.predicted_display_time, views

    def bind_eye_framebuffer(self, eye_index: int) -> int:
        sc_info = self.swapchains[eye_index]
        image_index = xr.acquire_swapchain_image(sc_info.handle, xr.SwapchainImageAcquireInfo())
        xr.wait_swapchain_image(sc_info.handle, xr.SwapchainImageWaitInfo(timeout=xr.INFINITE_DURATION))

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._fbo)
        GL.glFramebufferTexture2D(
            GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
            GL.GL_TEXTURE_2D, sc_info.images[image_index], 0,
        )
        GL.glFramebufferRenderbuffer(
            GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
            GL.GL_RENDERBUFFER, self._depth_buffers[eye_index],
        )
        GL.glViewport(0, 0, sc_info.width, sc_info.height)
        return image_index

    def release_eye_framebuffer(self, eye_index: int) -> None:
        GL.glFlush()
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        xr.release_swapchain_image(self.swapchains[eye_index].handle, xr.SwapchainImageReleaseInfo())

    def frame_end(self, display_time: int, views: list[xr.View]) -> None:
        projection_views = []
        for i, view in enumerate(views):
            sc_info = self.swapchains[i]
            projection_views.append(
                xr.CompositionLayerProjectionView(
                    pose=view.pose,
                    fov=view.fov,
                    sub_image=xr.SwapchainSubImage(
                        swapchain=sc_info.handle,
                        image_rect=xr.Rect2Di(
                            offset=xr.Offset2Di(0, 0),
                            extent=xr.Extent2Di(sc_info.width, sc_info.height),
                        ),
                        image_array_index=0,
                    ),
                )
            )

        projection_layer = xr.CompositionLayerProjection(
            space=self._space,
            views=projection_views,
        )

        layers = [ctypes.cast(ctypes.pointer(projection_layer), ctypes.POINTER(xr.CompositionLayerBaseHeader))]
        xr.end_frame(
            self._session,
            xr.FrameEndInfo(
                display_time=display_time,
                environment_blend_mode=xr.EnvironmentBlendMode.OPAQUE,
                layers=layers if views else [],
            ),
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._session is not None:
            if self._session_state in (xr.SessionState.READY, xr.SessionState.SYNCHRONIZED,
                                        xr.SessionState.VISIBLE, xr.SessionState.FOCUSED):
                try:
                    xr.request_exit_session(self._session)
                except xr.ResultException:
                    pass
            for sc_info in self.swapchains:
                xr.destroy_swapchain(sc_info.handle)
            if self._space is not None:
                xr.destroy_space(self._space)
            xr.destroy_session(self._session)
        if self._instance is not None:
            xr.destroy_instance(self._instance)
        if self._fbo:
            GL.glDeleteFramebuffers(1, [self._fbo])
        for db in self._depth_buffers:
            GL.glDeleteRenderbuffers(1, [db])
        if self._window:
            glfw.destroy_window(self._window)
        glfw.terminate()
