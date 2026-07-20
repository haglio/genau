from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace
from pathlib import Path

import pygame

from genau.drive_hud import DriveHud, read_drive
from genau.tcode import UdpTCodeSink
from player_core.file_channel import append_command, consume_command_file, read_paused_state
from player_core.mpv_player import MpvPlayer
from player_core.status import StatusWriter

from .cli import (
    DEFAULT_CONFIG,
    audio_muted,
    build_parser,
    library_source,
    load_config,
    mode_memory,
    resolve_playlist,
)
from .clip_jumps import ClipJumps
from .clip_nav import ClipNav
from .console import ConsoleModel, genau_drives, read_console
from .hud import ModeHud, NauHud, NauHudPainter, hud_xy
from .notice import NoticeWriter
from .library_source import DEFAULT_MODE, LENGTH_MODES, next_length_mode
from .mode_memory import RememberedMode
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
from player_core.volume import (
    VolumeHud,
    VolumeHudPainter,
    chip_local,
    chip_xy,
    hit_part,
    volume_at,
)
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
_OV_CONSOLE = 6
_OV_VOLUME = 7

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


def _set_aumid(config_path) -> None:
    try:
        from genau.win32 import take_taskbar_identity
        take_taskbar_identity(
            _APP_USER_MODEL_ID, include="nau", exclude="genau", config_path=config_path,
        )
    except Exception:
        pass



def _open_window(args):
    """Create Nau's window and return its surface.

    Comes before any library work: reading the library is the long part of
    startup, and until the window exists there is nowhere to say so — which is
    also why Fun Time, which waits on this window by caption, now finds it
    within its budget however cold the duration cache is.

    Borderless, like the satellites: the mode this window's title bar used to name
    is on the in-video HUD now, so the bar only took space.  With no chrome the
    client area is the whole rect Fun Time sizes it to, and the caption survives
    only for Alt-Tab and the window lookup.
    """
    pygame.init()
    if args.x is not None and args.y is not None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{args.x},{args.y}"
    icon = _load_icon_surface()
    if icon is not None:
        pygame.display.set_icon(icon)  # must precede set_mode to take effect
    screen = pygame.display.set_mode((args.width, args.height), pygame.NOFRAME)
    pygame.display.set_caption("Nau")
    return screen


def _run(args) -> int:
    _set_aumid(args.config)
    screen = _open_window(args)
    # mpv renders the video directly into this window; overlays go on top.  Until
    # it does, the window is the loading screen's to paint.
    wid = pygame.display.get_wm_info()["window"]

    # The mode this player was last in.  Fun Time resumes the playlist a session
    # closed on rather than rebuilding it, so the mode that chose those videos is
    # last session's too — and a list of files cannot say which.
    memory = mode_memory(args)
    remembered = memory.read()

    loading = LoadingScreen(screen)
    try:
        # The long part of startup, and so the part the loading screen reports.
        # Fun Time passes --playlist and owns its selection; standalone builds the
        # remembered mode's playlist itself. Either way the source (when present)
        # powers version cycling, the length modes, and folding each video's
        # versions to a single rotation slot.
        source = library_source(args, on_progress=loading.update)
        pairs = resolve_playlist(
            args, source=source, mode=remembered.length_mode or DEFAULT_MODE)
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
    length_mode = (remembered.length_mode or DEFAULT_MODE) if source is not None else ""
    # Fun Time's F-mode narrows the playlist it writes to the scripted videos.
    # The result is indistinguishable from any other playlist here, so this only
    # ever comes from Fun Time saying so — and defaults off, because a session
    # that is never told is a session where nothing narrowed it.
    f_mode = False
    # Whether a bare, player-less command lands here rather than on a satellite.
    # Fun Time tracks it and says so; a session never told is one where the
    # satellites have had every word, which is where a fresh session starts.
    active = False
    # The primary display's sound, as Fun Time publishes it.  Nau's own mpv is one
    # of two sinks it drives (Genau's clip audio is the other), so the level here
    # is drawn and reported, never decided: a press asks Fun Time and the answer
    # comes back down the same channel.
    volume_hud = VolumeHud()
    volume_painter = VolumeHudPainter()
    heatmap = HeatmapStrip()
    console_hud = NauHudPainter()
    # What Fun Time says about the primary slot, and what Genau says it is doing
    # to the device.  Both arrive published; before the first read the console
    # still draws, with the player's own controls and nothing claimed about the
    # room around it.
    console = ConsoleModel()
    drive: DriveHud | None = None
    # Where the cursor is over the console, so a button can name itself on hover.
    hover: tuple[int, int] | None = None
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
    # Entering a compilation swaps the playlist in memory only, and Fun Time can
    # only rotate its resumed file onto a video the file contains — which a
    # compilation's clips often are not.  So the clip is remembered too, and the
    # volume comes back around it rather than around whatever the list leads with.
    jumps.resume(
        remembered.compilation,
        Path(remembered.video) if remembered.video else None,
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

    def _end_compilation() -> None:
        """Out of a compilation without naming a length: the mode that was
        feeding the playlist when it was entered is the one still held here,
        since PLAY_COMPILATION replaces the playlist but not the mode.  The clip
        on screen keeps playing — leaving is about what "next" reaches."""
        if source is None:
            return
        jumps.end_compilation(source.playlist_for(length_mode))

    def _set_f_mode(active: bool) -> None:
        nonlocal f_mode
        f_mode = active

    def _set_active(has_floor: bool) -> None:
        nonlocal active
        active = has_floor

    def _set_volume_hud(level: int, muted: bool) -> None:
        nonlocal volume_hud
        volume_hud = VolumeHud(volume=level, muted=muted)

    def _timeline_h() -> int:
        # The heatmap strip when scripted (may be taller while recording),
        # else the plain progress bar — always present so every video has a
        # clickable timeline.
        return heatmap.height or TIMELINE_HEIGHT

    def _post(command: str) -> None:
        """Ask Fun Time for something, on the channel its dashboard uses.

        Every control on this HUD asks rather than acts — the console's buttons
        because the verbs are the room's, not this player's, and the volume slider
        because Fun Time holds the authority over the primary display's sound.

        Appended, because that file carries every mouse- and voice-driven writer
        at once and the dispatch loop drains it a tick at a time.  Standalone
        (no Fun Time) there is nowhere to ask, so a control is inert rather than
        pretending: it goes on showing whatever is actually the case.
        """
        if args.dashboard_cmd_file is not None:
            append_command(args.dashboard_cmd_file, command)

    def _press_volume(cx: int, cy: int) -> bool:
        """Take a press at chip-local ``(cx, cy)``; False if it missed the chip.

        The new level is shown at once and asked for at the same time: Fun Time
        holds the authority and its answer is a tick away, and a slider that waits
        for it drags a frame behind the pointer.  Its answer overwrites this one
        either way, so an ignored press corrects itself rather than sticking.
        """
        nonlocal volume_hud
        part = hit_part(cx, cy)
        if part == "mute":
            volume_hud = replace(volume_hud, muted=not volume_hud.muted)
            _post("audio_unmute" if not volume_hud.muted else "audio_mute")
        elif part == "track":
            level = volume_at(cx)
            volume_hud = VolumeHud(volume=level, muted=False)
            _post(f"audio_set_volume|{level}")
        return bool(part)

    def _click(mx: int, my: int, win_w: int, win_h: int) -> None:
        # The volume control first — it floats over the video, so a press on it is
        # never also a press on what is behind it.
        if _press_volume(*chip_local(mx, my, win_w=win_w, win_h=win_h,
                                     timeline_h=_timeline_h())):
            return
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
                pressed = console_hud.command_at(*ev.pos)
                if pressed:
                    _post(pressed)
                else:
                    # A press that missed every button falls through to the video,
                    # where it seeks or pauses as it always did.
                    _click(ev.pos[0], ev.pos[1], win_w, win_h)
            elif ev.type == pygame.MOUSEMOTION:
                hover = console_hud.hover_at(*ev.pos)
                if ev.buttons[0]:
                    # Dragging along the track keeps setting the level, the way
                    # every volume slider does; a drag that began elsewhere misses
                    # the chip and does nothing.
                    cx, cy = chip_local(*ev.pos, win_w=win_w, win_h=win_h,
                                        timeline_h=_timeline_h())
                    if hit_part(cx, cy) == "track":
                        _press_volume(cx, cy)
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
                    end_compilation=_end_compilation,
                    set_f_mode=_set_f_mode,
                    set_active=_set_active,
                    set_volume_hud=_set_volume_hud,
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

        # Write the mode down whenever it moves, whichever path moved it, so the
        # next session — which opens on this one's resumed playlist — can name it
        # and re-enter the volume it was in.
        mode_now = RememberedMode(
            length_mode=length_mode, compilation=jumps.compilation,
            # Only while inside one: the clip is remembered as the volume's
            # anchor, and outside a compilation there is no volume to anchor.
            video=str(session.current_video) if jumps.compilation else "",
        )
        if mode_now != remembered:
            remembered = mode_now
            memory.write(mode_now)

        # The top-left column: the console — the dot saying whether a bare
        # command lands here, what is selecting this playlist, what is driving the
        # device, and every control Fun Time's dashboard used to hold for this
        # slot — then the video's name and its playback rate.
        if args.console_file is not None:
            console = read_console(args.console_file) or console
        if args.drive_file is not None and genau_drives(console.mode):
            drive = read_drive(args.drive_file) or drive
        else:
            drive = None
        left, top = hud_xy()
        panel = console_hud.bgra(NauHud(
            modes=ModeHud(
                length_mode=length_mode, compilation=jumps.compilation,
                position=session.index + 1, total=len(session.playlist),
                f_mode=f_mode, active=active,
            ),
            console=console,
            drive=drive,
        ), hover=hover)
        player.overlay(_OV_CONSOLE, left, top, panel)
        top += panel.shape[0] + _STACK_GAP

        name = name_bgra(session.current_video.stem)
        player.overlay(_OV_NAME, left, top, name)
        top += name.shape[0] + _STACK_GAP

        if session.speed != 1.0:
            player.overlay(_OV_SPEED, left, top, speed_bgra(session.speed))
        else:
            player.remove_overlay(_OV_SPEED)

        # The volume control, at the right-hand end of the row above the timeline —
        # beside the transport, where a player's has always been.
        vx, vy = chip_xy(win_w=win_w, win_h=win_h, timeline_h=_timeline_h())
        player.overlay(_OV_VOLUME, vx, vy, volume_painter.bgra(volume_hud))

        _draw_loop_thumbnails(player, loop_thumbs, session, heatmap, win_w, win_h)

        clock.tick(60)

    session.close()
    pygame.quit()
    return 0
