from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pygame

from genau.pygame_view import get_window_chrome_height
from genau.runtime_support import consume_command_file, read_paused_state
from genau.tcode import UdpTCodeSink

from .cli import (
    DEFAULT_CONFIG,
    audio_muted,
    build_parser,
    library_source,
    load_config,
    resolve_playlist,
)
from .library_source import DEFAULT_MODE, OTHER_MODE
from .mpv_player import MpvPlayer
from .overlay import (
    TIMELINE_HEIGHT,
    HeatmapStrip,
    LoopThumbCapture,
    badge_bgra,
    badge_xy,
    heatmap_bgra,
    indicator_bgra,
    indicator_for,
    indicator_xy,
    label_xs,
    name_bgra,
    progress_bar_bgra,
    record_available,
    time_to_x,
)
from .playlist import read_playlist
from .runtime import SEEK_STEP_MS, apply_command
from .session import PlayerSession
from .status import StatusWriter
from .tcode_driver import FunscriptTCodeDriver

logger = logging.getLogger(__name__)

_APP_USER_MODEL_ID = "Nau.App"

# Overlay ids (stable so each frame updates in place).
_OV_HEATMAP = 0
_OV_INDICATOR = 1
_OV_BADGE = 2
_OV_NAME = 3
_OV_IN_THUMB = 4
_OV_OUT_THUMB = 5

_ICON_PATH = Path(__file__).resolve().parent.parent / "nau_icon.ico"


def _load_icon_surface():
    """Nau's window icon (pink N) as a pygame surface, or None."""
    if not _ICON_PATH.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(_ICON_PATH).convert("RGBA")
        return pygame.image.fromstring(img.tobytes(), img.size, "RGBA")
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = load_config(DEFAULT_CONFIG)
    args = build_parser(config).parse_args(argv)

    if args.config != DEFAULT_CONFIG:
        config = load_config(args.config)
        args = build_parser(config).parse_args(argv)

    source = library_source(args)
    pairs = source.playlist_for(DEFAULT_MODE) if source is not None else resolve_playlist(args)
    if not pairs:
        logger.error("No videos found (need --playlist or --videos-dir/--scripts-dir)")
        return 1
    scripted = sum(1 for _, fs in pairs if fs is not None)
    logger.info("Found %d video(s), %d with funscripts", len(pairs), scripted)

    return _run(args, pairs, source)


def _draw_loop_thumbnails(player, loop_thumbs, session, heatmap, win_w, win_h) -> None:
    """Capture (on demand) and draw the loop in/out frame thumbnails above
    their timeline marks."""
    bounds = session.loop_bounds
    which = loop_thumbs.needed(session.loop_state, bounds, session.position_ms)
    if which is not None:
        thumb = player.screenshot_bgra()
        if thumb is not None:
            loop_thumbs.set(which, thumb)
    if bounds is None:
        player.remove_overlay(_OV_IN_THUMB)
        player.remove_overlay(_OV_OUT_THUMB)
        return
    start_ms, end_ms = heatmap.window
    in_x = time_to_x(bounds[0], start_ms, end_ms, win_w)
    out_x = time_to_x(bounds[1], start_ms, end_ms, win_w)
    in_t, out_t = loop_thumbs.in_thumb, loop_thumbs.out_thumb
    iw = in_t.shape[1] if in_t is not None else 1
    ow = out_t.shape[1] if out_t is not None else 1
    ix, ox = label_xs(in_x, out_x, iw, ow, win_w)
    strip_h = heatmap.height or TIMELINE_HEIGHT
    if in_t is not None:
        y = win_h - strip_h - in_t.shape[0] - 2
        player.overlay(_OV_IN_THUMB, ix, y, in_t)
    if out_t is not None:
        y = win_h - strip_h - out_t.shape[0] - 2
        player.overlay(_OV_OUT_THUMB, ox, y, out_t)


def _set_aumid() -> None:
    try:
        from genau.win32 import set_app_user_model_id, stamp_pinned_shortcuts
        set_app_user_model_id(_APP_USER_MODEL_ID)
        stamp_pinned_shortcuts(_APP_USER_MODEL_ID, include="nau", exclude="genau")
    except Exception:
        pass


def _run(args, pairs: list[tuple[Path, Path | None]], source=None) -> int:
    _set_aumid()
    pygame.init()
    chrome = get_window_chrome_height()
    client_h = max(1, args.height - chrome)
    if args.x is not None and args.y is not None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{args.x},{args.y + chrome}"
    _icon = _load_icon_surface()
    if _icon is not None:
        pygame.display.set_icon(_icon)  # must precede set_mode to take effect
    screen = pygame.display.set_mode((args.width, client_h))
    pygame.display.set_caption("Nau")
    clock = pygame.time.Clock()
    # mpv renders the video directly into this window; overlays go on top.
    wid = pygame.display.get_wm_info()["window"]

    paused_file: Path | None = args.paused_file
    command_file: Path | None = args.command_file
    start_paused = paused_file is not None and read_paused_state(paused_file, logger=logger)

    player = MpvPlayer(wid, muted=audio_muted(args))
    session = PlayerSession(
        pairs,
        player=player,
        tcode=FunscriptTCodeDriver(UdpTCodeSink(args.tcode_host, args.tcode_port)),
        start_paused=start_paused,
        version_index=source.version_index if source is not None else None,
    )
    length_mode = DEFAULT_MODE
    heatmap = HeatmapStrip()
    loop_thumbs = LoopThumbCapture()
    status_writer = StatusWriter(args.status_file) if args.status_file else None
    stop_event = threading.Event()

    def _reload_playlist() -> None:
        if args.playlist is not None:
            session.replace_playlist(read_playlist(Path(args.playlist)))

    def _toggle_length_mode() -> None:
        nonlocal length_mode
        if source is None:
            return
        length_mode = OTHER_MODE if length_mode == DEFAULT_MODE else DEFAULT_MODE
        logger.info("Length mode: %s", length_mode)
        session.load_playlist(source.playlist_for(length_mode))

    def _timeline_h() -> int:
        # The heatmap strip when scripted (may be taller while recording),
        # else the plain progress bar — always present so every video has a
        # clickable timeline.
        return heatmap.height or TIMELINE_HEIGHT

    def _click_to_seek(mx: int, my: int, win_w: int, win_h: int) -> None:
        # Click on the timeline seeks there; a click on the video toggles pause.
        if my >= win_h - _timeline_h():
            start_ms, end_ms = heatmap.window
            if end_ms <= start_ms:
                end_ms = start_ms + session.duration_ms
            frac = min(1.0, max(0.0, mx / max(1, win_w)))
            session.seek_to(start_ms + frac * (end_ms - start_ms))
        else:
            session.toggle_pause()

    while not stop_event.is_set():
        win_w, win_h = screen.get_size()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                stop_event.set()
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                _click_to_seek(ev.pos[0], ev.pos[1], win_w, win_h)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_q and ev.mod & pygame.KMOD_CTRL:
                    stop_event.set()
                elif ev.key == pygame.K_ESCAPE:
                    session.toggle_pause()
                elif ev.key == pygame.K_r:
                    session.record_down()
                elif ev.key == pygame.K_LEFTBRACKET:
                    session.step(-1)
                elif ev.key == pygame.K_RIGHTBRACKET:
                    session.step(1)
                elif ev.key == pygame.K_MINUS:
                    session.seek_by(-SEEK_STEP_MS)
                elif ev.key == pygame.K_EQUALS:
                    session.seek_by(SEEK_STEP_MS)
                elif ev.key == pygame.K_v:
                    session.cycle_version()
                elif ev.key == pygame.K_l:
                    _toggle_length_mode()
            elif ev.type == pygame.KEYUP:
                if ev.key == pygame.K_r:
                    session.record_up()

        if paused_file is not None:
            session.set_paused(read_paused_state(paused_file, logger=logger))
        if command_file is not None:
            for cmd in consume_command_file(command_file, logger=logger, uppercase=False):
                apply_command(
                    cmd, session,
                    stop_event=stop_event,
                    reload_playlist=_reload_playlist,
                    toggle_length_mode=_toggle_length_mode,
                )

        session.advance()
        if status_writer is not None:
            status_writer.write(session)

        # --- overlays on top of mpv's video ---
        heatmap.update(
            session.current_video, session.current_funscript, session.duration_ms, win_w,
            loop_state=session.loop_state,
            record_in_ms=session.record_in_ms,
            position_ms=session.position_ms,
        )
        hb = heatmap_bgra(heatmap, session.position_ms, session.loop_bounds, win_w)
        if hb is None:
            # Unscripted video: a plain clickable progress bar instead.
            hb = progress_bar_bgra(session.position_ms, session.duration_ms, win_w)
        player.overlay(_OV_HEATMAP, 0, win_h - hb.shape[0], hb)

        name = name_bgra(session.current_video.stem)
        player.overlay(_OV_NAME, 8, 8, name)

        ind = indicator_bgra(indicator_for(session.loop_state, paused=session.is_paused))
        ix, iy = indicator_xy(win_w)
        player.overlay(_OV_INDICATOR, ix, iy, ind)

        if not record_available(has_funscript=session.has_funscript):
            badge = badge_bgra()
            bx, by = badge_xy(win_w, badge.shape[1])
            player.overlay(_OV_BADGE, bx, by, badge)
        else:
            player.remove_overlay(_OV_BADGE)

        _draw_loop_thumbnails(player, loop_thumbs, session, heatmap, win_w, win_h)

        clock.tick(60)

    session.close()
    pygame.quit()
    return 0
