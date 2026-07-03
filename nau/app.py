from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pygame
from pygame._sdl2.video import Renderer, Texture, Window

from genau.pygame_view import get_window_chrome_height, load_window_icon
from genau.tcode import UdpTCodeSink

from .discovery import discover_videos
from .overlay import RecordingStrip, draw_indicator, draw_strip, indicator_for
from .playback import AudioPlayer, PlaybackClock, VideoStream
from .session import PlayerSession
from .tcode_driver import FunscriptTCodeDriver

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "genau_config.json"
_ICON_PATH = Path(__file__).resolve().parent.parent / "nau_icon.ico"
_APP_USER_MODEL_ID = "Nau.App"
_SEEK_STEP_MS = 10_000


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


def _load_config(config_path: Path) -> dict:
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def _build_parser(config: dict) -> argparse.ArgumentParser:
    nau = config.get("nau", {})
    p = argparse.ArgumentParser(description="Nau — funscript video player")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--videos-dir", type=Path, default=nau.get("videos_dir"))
    p.add_argument("--scripts-dir", type=Path, default=nau.get("scripts_dir"))
    p.add_argument("--width", type=int, default=1200)
    p.add_argument("--height", type=int, default=900)
    p.add_argument("--tcode-host", default=nau.get("tcode_udp_host", "127.0.0.1"))
    p.add_argument("--tcode-port", type=int, default=nau.get("tcode_udp_port", 50557))
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = _load_config(_DEFAULT_CONFIG)
    args = _build_parser(config).parse_args(argv)

    if args.config != _DEFAULT_CONFIG:
        config = _load_config(args.config)
        args = _build_parser(config).parse_args(argv)

    if args.videos_dir is None or args.scripts_dir is None:
        logger.error("--videos-dir and --scripts-dir are required")
        return 1

    pairs = discover_videos(Path(args.videos_dir), Path(args.scripts_dir))
    if not pairs:
        logger.error("No videos found")
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
    load_window_icon(window, _ICON_PATH)
    renderer = Renderer(window, accelerated=True)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 14)

    session = PlayerSession(
        pairs,
        video=VideoStream(),
        audio=AudioPlayer(),
        clock=PlaybackClock(),
        tcode=FunscriptTCodeDriver(
            UdpTCodeSink(args.tcode_host, args.tcode_port),
        ),
    )
    strip = RecordingStrip(
        tile_height=max(32, client_h // 12), max_width=args.width,
    )
    running = True

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_q and ev.mod & pygame.KMOD_CTRL:
                    running = False
                elif ev.key == pygame.K_ESCAPE:
                    session.toggle_pause()
                elif ev.key == pygame.K_SPACE:
                    session.record_down()
                elif ev.key == pygame.K_LEFTBRACKET:
                    session.step(-1)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    session.step(1)
                elif ev.key == pygame.K_MINUS:
                    session.seek_by(-_SEEK_STEP_MS)
                elif ev.key == pygame.K_EQUALS:
                    session.seek_by(_SEEK_STEP_MS)
            elif ev.type == pygame.KEYUP:
                if ev.key == pygame.K_SPACE:
                    session.record_up()

        display_frame = session.advance()
        strip.update(session.loop_state, session.position_ms, display_frame)

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

        draw_strip(renderer, strip, session.position_ms, win_h)
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
