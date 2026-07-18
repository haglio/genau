"""Run loop for a native satellite player: a silent mpv window fun_time drives.

The satellite half of Nau's app shell, stripped to essentials — no funscript,
tcode, heatmap, in-window overlays, record or version cycling.  mpv renders the
video into a pygame/SDL window; fun_time positions that window by HWND after
launch and drives playback through the command + paused files, reading back the
status file.  The lock HUD is a separate overlay window (fun_time's lock_hud), so
the satellite draws nothing on top of the video itself.

Not unit-tested: it needs the libmpv DLL and a real window.  The pure control
logic it drives lives in satellite.session / satellite.runtime, tested against a
fake player.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pygame

from genau.runtime_support import consume_command_file, read_paused_state
from nau.mpv_player import MpvPlayer

from .cli import audio_muted, build_parser, resolve_playlist
from .runtime import apply_command
from .session import SatelliteSession
from .status import StatusWriter

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    playlist = resolve_playlist(args)
    if not playlist:
        logger.error("No videos to play (need --playlist)")
        return 1
    logger.info("Satellite playing %d clip(s)", len(playlist))
    return _run(args, playlist)


def _run(args, playlist: list[Path]) -> int:
    pygame.init()
    if args.x is not None and args.y is not None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{args.x},{args.y}"
    # Borderless: the satellites replace VLC, which filled its whole slot with no
    # title bar, so the video has to fill the rect too.  mpv paints into this
    # window via its HWND (we never blit the surface); the sequencer then sizes
    # the window to the portrait/landscape rect, and with no chrome the client
    # area IS the rect.
    pygame.display.set_mode((args.width, args.height), pygame.NOFRAME)
    pygame.display.set_caption("Satellite")
    clock = pygame.time.Clock()
    # mpv renders the video directly into this window; the lock HUD overlays it
    # from a separate window, so nothing is drawn here.
    wid = pygame.display.get_wm_info()["window"]

    paused_file: Path | None = args.paused_file
    command_file: Path | None = args.command_file
    start_paused = paused_file is not None and read_paused_state(paused_file, logger=logger)

    # loop_file=False so end-of-file advances the playlist; the lock toggles it on.
    # prefetch=True so mpv opens the next clip before the current ends and the
    # auto-advance is seamless instead of a cold on-screen reload.
    player = MpvPlayer(wid, muted=audio_muted(args), loop_file=False, prefetch=True)
    session = SatelliteSession(playlist, player=player, start_paused=start_paused)
    status_writer = StatusWriter(args.status_file) if args.status_file else None
    stop_event = threading.Event()

    def _reload_playlist() -> None:
        reloaded = resolve_playlist(args)
        if reloaded:
            session.replace_playlist(reloaded)

    while not stop_event.is_set():
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                stop_event.set()
            elif (ev.type == pygame.KEYDOWN and ev.key == pygame.K_q
                  and ev.mod & pygame.KMOD_CTRL):
                stop_event.set()

        if paused_file is not None:
            session.set_paused(read_paused_state(paused_file, logger=logger))
        if command_file is not None:
            for cmd in consume_command_file(command_file, logger=logger, uppercase=False):
                apply_command(cmd, session, stop_event=stop_event, reload_playlist=_reload_playlist)

        session.advance()
        if status_writer is not None:
            status_writer.write(session)

        clock.tick(60)

    session.close()
    pygame.quit()
    return 0
