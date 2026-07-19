from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pygame

from genau.pygame_view import get_window_chrome_height
from genau.tcode import UdpTCodeSink
from player_core.file_channel import consume_command_file, read_paused_state
from player_core.mpv_player import MpvPlayer
from player_core.status import StatusWriter

from .cli import (
    DEFAULT_CONFIG,
    audio_muted,
    build_parser,
    library_source,
    load_config,
    resolve_playlist,
)
from .clip_jumps import ClipJumps
from .clip_nav import ClipNav
from .hud import ModeHud, ModeHudPainter, hud_xy
from .notice import NoticeWriter
from .library_source import DEFAULT_MODE, LENGTH_MODES, next_length_mode
from .loading import LoadingCancelled, LoadingScreen
from .overlay import (
    TIMELINE_HEIGHT,
    HeatmapStrip,
    LoopThumbCapture,
    bar_track_x,
    heatmap_bgra,
    label_xs,
    name_bgra,
    progress_bar_bgra,
    speed_bgra,
    time_to_x,
)
from .runtime import SEEK_STEP_MS, apply_command
from .session import PlayerSession
from .status import status_fields
from .tcode_driver import FunscriptTCodeDriver

logger = logging.getLogger(__name__)

_APP_USER_MODEL_ID = "Nau.App"

# Overlay ids (stable so each frame updates in place).
_OV_HEATMAP = 0
_OV_SPEED = 2
_OV_NAME = 3
_OV_IN_THUMB = 4
_OV_OUT_THUMB = 5
_OV_MODE = 6

# Between the stacked overlays in the top-left column: the mode HUD, the video's
# name, and the playback rate when it is off normal.
_STACK_GAP = 4

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

    return _run(args)


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
    tx0, tx1 = bar_track_x(win_w)  # thumbnails sit above their marks on the inset track
    track_w = tx1 - tx0
    in_x = tx0 + time_to_x(bounds[0], start_ms, end_ms, track_w)
    out_x = tx0 + time_to_x(bounds[1], start_ms, end_ms, track_w)
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


def _open_window(args):
    """Create Nau's window and return its surface.

    Comes before any library work: reading the library is the long part of
    startup, and until the window exists there is nowhere to say so — which is
    also why Fun Time, which waits on this window by caption, now finds it
    within its budget however cold the duration cache is.
    """
    pygame.init()
    chrome = get_window_chrome_height()
    client_h = max(1, args.height - chrome)
    if args.x is not None and args.y is not None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{args.x},{args.y + chrome}"
    icon = _load_icon_surface()
    if icon is not None:
        pygame.display.set_icon(icon)  # must precede set_mode to take effect
    screen = pygame.display.set_mode((args.width, client_h))
    pygame.display.set_caption("Nau")
    return screen


def _run(args) -> int:
    _set_aumid()
    screen = _open_window(args)
    # mpv renders the video directly into this window; overlays go on top.  Until
    # it does, the window is the loading screen's to paint.
    wid = pygame.display.get_wm_info()["window"]

    loading = LoadingScreen(screen)
    try:
        # The long part of startup, and so the part the loading screen reports.
        # Fun Time passes --playlist and owns its selection; standalone falls back
        # to the source's full-length playlist. Either way the source (when
        # present) powers version cycling, the shorts/full-length toggle, and
        # folding each video's versions to a single rotation slot.
        source = library_source(args, on_progress=loading.update)
        pairs = resolve_playlist(args, source=source)
    except LoadingCancelled:
        logger.info("Closed while loading; never started playback")
        pygame.quit()
        return 0
    if not pairs:
        logger.error("No videos found (need --playlist or --videos-dir/--scripts-dir)")
        pygame.quit()
        return 1
    scripted = sum(1 for _, fs in pairs if fs is not None)
    logger.info("Found %d video(s), %d with funscripts", len(pairs), scripted)

    clock = pygame.time.Clock()
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
    # Empty when there is no library behind the playlist (Fun Time can hand Nau
    # one without library dirs): no length filter is running, so the HUD has no
    # mode to name and the toggle has nothing to rebuild.
    length_mode = DEFAULT_MODE if source is not None else ""
    # Genau's HUD holds the top-left corner in Hybrid; Fun Time says when.
    hybrid = False
    heatmap = HeatmapStrip()
    mode_hud = ModeHudPainter()
    loop_thumbs = LoopThumbCapture()
    status_writer = StatusWriter(args.status_file, status_fields) if args.status_file else None
    stop_event = threading.Event()

    # Clip navigation: a clip carved from a compilation records its siblings,
    # order, and source scene in its sidecar (see nau.clip_nav). Built once over
    # the whole discovered library so "compilation"/"full video"/"money shot" can
    # jump from whatever is on screen.  With no library there is nothing to jump
    # to, and an empty index answers that without a special case.
    entries = source.entries if source is not None else []
    clip_nav = ClipNav.build(
        [e.video for e in entries] + [c.video for c in (source.clips if source else [])],
        source.metadata_root if source is not None else None,
    )
    jumps = ClipJumps(
        clip_nav, session, {e.video: e.funscript for e in entries},
        NoticeWriter(getattr(args, "notice_file", None)),
    )

    def _reload_playlist() -> None:
        if args.playlist is not None:
            session.replace_playlist(resolve_playlist(args, source=source))
            jumps.leave_compilation()

    def _set_length_mode(mode: str) -> None:
        nonlocal length_mode
        if source is None:
            return
        mode = mode.strip().lower()
        if mode not in LENGTH_MODES:
            return
        # Rebuild even when the mode is unchanged: PLAY_COMPILATION swaps the
        # playlist for one volume's clips, and asking for a length again is how
        # you get back out of it.
        length_mode = mode
        jumps.leave_compilation()
        logger.info("Length mode: %s", length_mode)
        session.load_playlist(source.playlist_for(length_mode))

    def _toggle_length_mode() -> None:
        _set_length_mode(next_length_mode(length_mode))

    def _set_hybrid(active: bool) -> None:
        nonlocal hybrid
        hybrid = active

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
            # Both the heatmap strip and the plain bar are inset to the same
            # track, so a click maps onto it the same way.
            x0, x1 = bar_track_x(win_w)
            frac = min(1.0, max(0.0, (mx - x0) / max(1, x1 - x0)))
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
                    set_length_mode=_set_length_mode,
                    play_compilation=jumps.play_compilation,
                    play_full_vid=jumps.play_full_vid,
                    play_money_shot=jumps.play_money_shot,
                    set_hybrid=_set_hybrid,
                )

        session.advance()
        if status_writer is not None:
            status_writer.write(session)

        # --- overlays on top of mpv's video ---
        # The heatmap fills the inset track, so build its colour row at track
        # width; heatmap_bgra frames it full-width to line up with the plain bar.
        tx0, tx1 = bar_track_x(win_w)
        heatmap.update(
            session.current_video, session.current_funscript, session.duration_ms,
            tx1 - tx0,
            loop_state=session.loop_state,
            record_in_ms=session.record_in_ms,
            position_ms=session.position_ms,
        )
        hb = heatmap_bgra(heatmap, session.position_ms, session.loop_bounds, win_w)
        if hb is None:
            # Unscripted video: a plain clickable progress bar instead, still
            # showing the playcursor and any loop in/out marks.
            hb = progress_bar_bgra(
                session.position_ms, session.duration_ms, session.loop_bounds,
                win_w, record_in_ms=session.record_in_ms,
            )
        player.overlay(_OV_HEATMAP, 0, win_h - hb.shape[0], hb)

        # The top-left column, stacked: which mode is selecting what plays (the
        # length filter, or the compilation holding the playlist), then the
        # video's name, then its playback rate when that is off normal.
        left, top = hud_xy(hybrid=hybrid)
        modes = mode_hud.bgra(ModeHud(
            length_mode=length_mode, compilation=jumps.compilation,
            position=session.index + 1, total=len(session.playlist),
        ))
        if modes is None:
            player.remove_overlay(_OV_MODE)
        else:
            player.overlay(_OV_MODE, left, top, modes)
            top += modes.shape[0] + _STACK_GAP

        name = name_bgra(session.current_video.stem)
        player.overlay(_OV_NAME, left, top, name)
        top += name.shape[0] + _STACK_GAP

        if session.speed != 1.0:
            player.overlay(_OV_SPEED, left, top, speed_bgra(session.speed))
        else:
            player.remove_overlay(_OV_SPEED)

        _draw_loop_thumbnails(player, loop_thumbs, session, heatmap, win_w, win_h)

        clock.tick(60)

    session.close()
    pygame.quit()
    return 0
