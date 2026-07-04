from __future__ import annotations

import logging
import threading
from pathlib import Path

import pygame
from pygame._sdl2.video import Renderer, Texture, Window

from genau.pygame_view import get_window_chrome_height, load_window_icon
from genau.runtime_support import consume_command_file, read_paused_state
from genau.tcode import UdpTCodeSink

from .cli import DEFAULT_CONFIG, audio_muted, build_parser, load_config, resolve_playlist
from .overlay import (
    HeatmapStrip,
    LoopThumbnails,
    draw_heatmap,
    draw_indicator,
    indicator_for,
)
from .playback import PlaybackClock, VideoStream, build_audio_player
from .playlist import read_playlist
from .runtime import SEEK_STEP_MS, apply_command
from .session import PlayerSession
from .status import StatusWriter
from .tcode_driver import FunscriptTCodeDriver

logger = logging.getLogger(__name__)

_ICON_PATH = Path(__file__).resolve().parent.parent / "nau_icon.ico"
_APP_USER_MODEL_ID = "Nau.App"


def _compute_video_rect(
    video_w: int, video_h: int, win_w: int, win_h: int,
) -> tuple[int, int, int, int]:
    scale = min(win_w / video_w, win_h / video_h)
    w = int(video_w * scale)
    h = int(video_h * scale)
    x = (win_w - w) // 2
    y = (win_h - h) // 2
    return x, y, w, h


def _format_time(ms: float) -> str:
    total_s = int(ms / 1000)
    m, s = divmod(total_s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = load_config(DEFAULT_CONFIG)
    args = build_parser(config).parse_args(argv)

    if args.config != DEFAULT_CONFIG:
        config = load_config(args.config)
        args = build_parser(config).parse_args(argv)

    pairs = resolve_playlist(args)
    if not pairs:
        logger.error("No videos found (need --playlist or --videos-dir/--scripts-dir)")
        return 1
    scripted = sum(1 for _, fs in pairs if fs is not None)
    logger.info("Found %d video(s), %d with funscripts", len(pairs), scripted)

    return _run(args, pairs)


def _set_aumid() -> None:
    try:
        from genau.win32 import set_app_user_model_id, stamp_pinned_shortcuts
        set_app_user_model_id(_APP_USER_MODEL_ID)
        stamp_pinned_shortcuts(_APP_USER_MODEL_ID, include="nau", exclude="genau")
    except Exception:
        pass


def _run(args, pairs: list[tuple[Path, Path | None]]) -> int:
    _set_aumid()
    pygame.init()
    chrome = get_window_chrome_height()
    client_h = max(1, args.height - chrome)
    window = Window("Nau", size=(args.width, client_h))
    if args.x is not None and args.y is not None:
        window.position = (args.x, args.y + chrome)
    load_window_icon(window, _ICON_PATH)
    renderer = Renderer(window, accelerated=True)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 14)

    paused_file: Path | None = args.paused_file
    command_file: Path | None = args.command_file
    start_paused = paused_file is not None and read_paused_state(paused_file, logger=logger)

    session = PlayerSession(
        pairs,
        video=VideoStream(),
        audio=build_audio_player(muted=audio_muted(args)),
        clock=PlaybackClock(),
        tcode=FunscriptTCodeDriver(
            UdpTCodeSink(args.tcode_host, args.tcode_port),
        ),
        start_paused=start_paused,
    )
    heatmap = HeatmapStrip()
    loop_thumbs = LoopThumbnails()
    status_writer = StatusWriter(args.status_file) if args.status_file else None
    stop_event = threading.Event()

    def _reload_playlist() -> None:
        if args.playlist is not None:
            session.replace_playlist(read_playlist(Path(args.playlist)))

    while not stop_event.is_set():
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                stop_event.set()
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_q and ev.mod & pygame.KMOD_CTRL:
                    stop_event.set()
                elif ev.key == pygame.K_ESCAPE:
                    session.toggle_pause()
                elif ev.key == pygame.K_SPACE:
                    session.record_down()
                elif ev.key == pygame.K_LEFTBRACKET:
                    session.step(-1)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    session.step(1)
                elif ev.key == pygame.K_MINUS:
                    session.seek_by(-SEEK_STEP_MS)
                elif ev.key == pygame.K_EQUALS:
                    session.seek_by(SEEK_STEP_MS)
            elif ev.type == pygame.KEYUP:
                if ev.key == pygame.K_SPACE:
                    session.record_up()

        if paused_file is not None:
            session.set_paused(read_paused_state(paused_file, logger=logger))
        if command_file is not None:
            for cmd in consume_command_file(command_file, logger=logger, uppercase=False):
                apply_command(
                    cmd, session,
                    stop_event=stop_event,
                    reload_playlist=_reload_playlist,
                )

        display_frame = session.advance()
        loop_thumbs.update(
            session.loop_state, session.loop_bounds, session.position_ms, display_frame,
        )
        if status_writer is not None:
            status_writer.write(session)

        renderer.draw_color = (0, 0, 0, 255)
        renderer.clear()
        win_w, win_h = window.size
        if display_frame is not None:
            h, w = display_frame.shape[:2]
            surface = pygame.image.frombuffer(display_frame.tobytes(), (w, h), "RGB")
            texture = Texture.from_surface(renderer, surface)
            rx, ry, rw, rh = _compute_video_rect(w, h, win_w, win_h)
            texture.draw(dstrect=pygame.Rect(rx, ry, rw, rh))

        # Status overlay: video name + time; playback/loop state is the icon's job.
        pos_str = _format_time(session.position_ms)
        dur_str = _format_time(session.duration_ms)
        status = f"{session.current_video.stem}  {pos_str}/{dur_str}"

        text_surf = font.render(status, True, (255, 255, 255))
        pad = 6
        tw, th = text_surf.get_size()
        bg = pygame.Surface((tw + pad * 2, th + pad * 2), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 160))
        bg.blit(text_surf, (pad, pad))
        overlay = Texture.from_surface(renderer, bg)
        overlay.draw(dstrect=pygame.Rect(8, 8, tw + pad * 2, th + pad * 2))

        heatmap.update(
            session.current_video, session.current_funscript, session.duration_ms, win_w,
            loop_state=session.loop_state,
            record_in_ms=session.record_in_ms,
            position_ms=session.position_ms,
        )
        draw_heatmap(
            renderer, heatmap, session.position_ms, session.loop_bounds,
            win_w, win_h, thumbnails=loop_thumbs,
        )
        draw_indicator(
            renderer,
            indicator_for(session.loop_state, paused=session.is_paused),
            win_w,
        )

        renderer.present()
        clock.tick(session.fps)

    session.close()
    window.destroy()
    pygame.quit()
    return 0
