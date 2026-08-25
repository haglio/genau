from __future__ import annotations

import logging
import os
import threading
from functools import partial
from pathlib import Path

import pygame

from player_core.drive_readout import DriveHud, read_drive
from genau.pygame_view import get_window_chrome_height
from player_core.tcode import UdpTCodeSink
from player_core.file_channel import consume_command_file, read_paused_state
from player_core.mpv_player import MpvPlayer
from player_core.sdl_hints import deliver_the_focusing_click
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
from .dashboard import Dashboard
from .library_source import DEFAULT_MODE
from .drive_gate import DriveGate
from .modes import Modes, reload_playlist
from .pointer import Pointer
from .volume_control import VolumeControl
from .clip_nav import ClipNav
from player_core.console import ConsoleModel, genau_drives, read_console
from .display import Display
from .funscript_jumps import FunscriptJumps
from player_core.console_hud import (
    ConsoleHud,
    ConsolePainter,
    hud_xy,
    with_playback_speed,
)
from .notice import NoticeWriter
from .loading import LoadingCancelled, LoadingScreen
from .overlay import (
    HeatmapStrip,
    LoopThumbCapture,
    bar_track_x,
    heatmap_bgra,
    label_xs,
    progress_bar_bgra,
    time_to_x,
    timeline_height,
)
from .runtime import SEEK_STEP_MS, apply_command
from player_core.volume import VolumeHudPainter, chip_xy
from .session import PlayerSession
from .status import status_fields
from player_core.tcode_driver import FunscriptTCodeDriver

logger = logging.getLogger(__name__)

_APP_USER_MODEL_ID = "Nau.App"

# Overlay ids (stable so each frame updates in place).
_OV_HEATMAP = 0
_OV_IN_THUMB = 4
_OV_OUT_THUMB = 5
_OV_CONSOLE = 6
_OV_VOLUME = 7
# Every one of the above: what a blanked display takes down with the video.
_HUD_OVERLAYS = (_OV_HEATMAP, _OV_IN_THUMB, _OV_OUT_THUMB, _OV_CONSOLE, _OV_VOLUME)

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
    _name_this_process()
    config = load_config(DEFAULT_CONFIG)
    args = build_parser(config).parse_args(argv)

    if args.config != DEFAULT_CONFIG:
        config = load_config(args.config)
        args = build_parser(config).parse_args(argv)

    return _run(args)


def _name_this_process() -> None:
    """Leave ``launch_nau.vbs`` an interpreter that says "Nau" next time.

    Windows takes what it shows about a process from the file it was started
    from, so a plain ``pythonw.exe`` puts Nau in the task list as one more
    anonymous "Python" -- indistinguishable from Genau, which shares this venv,
    and from everything else the machine is running.

    Naming this process on the way in is the one thing that cannot be done:
    writing the copy takes the very interpreter being named.  So each run makes
    it for the run after and the launcher picks it up, which costs one launch,
    once.  Under Fun Time it is Fun Time's own copy that is running instead --
    Nau is one of its windows then, not an application the user opened -- and
    this still prepares the standalone one, which is about Nau's own shortcut
    rather than about who started this run.
    """
    try:
        from app_support.process_identity import ProcessNamer
        ProcessNamer("Nau", icon=_ICON_PATH).prepare_launcher("Nau")
    except Exception:
        pass  # Cosmetic: costs a name in the task list, never a launch.


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
    strip_h = timeline_height(heatmap)
    if in_t is not None:
        y = win_h - strip_h - in_t.shape[0] - 2
        player.overlay(_OV_IN_THUMB, ix, y, in_t)
    if out_t is not None:
        y = win_h - strip_h - out_t.shape[0] - 2
        player.overlay(_OV_OUT_THUMB, ox, y, out_t)


def _set_aumid(config_path, taskbar_identity: str | None = None) -> None:
    """Claim this window's place on the taskbar, before there is a window.

    *taskbar_identity* is an orchestrator saying these windows are its own: run
    under Fun Time, Nau is not an application the user launched but one window of
    the one they did, and it belongs on that button with the rest.  Told one, Nau
    takes it and stamps nothing — the pinned shortcut being stamped belongs to
    whoever owns that identity, and it is theirs to keep up to date.

    Standalone there is no one to say, so Nau is its own application as before.
    """
    try:
        from genau.win32 import take_taskbar_identity
        if taskbar_identity:
            from player_core.taskbar import set_app_user_model_id
            set_app_user_model_id(taskbar_identity)
            return
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

    Borderless under Fun Time, like the satellites: the mode this window's title
    bar used to name is on the in-video HUD now, so the bar only took space.  With
    no chrome the client area is the whole rect Fun Time sizes it to, and the
    caption survives only for Alt-Tab and the window lookup.  Standalone it keeps
    its chrome — so the window can be dragged and closed — and its client is sized
    down to leave the video inside the rect.
    """
    # Before the window exists, and before pygame.init(): SDL otherwise eats the
    # click that focuses this window, so every press on the console had to be
    # made twice — once to wake the window, once to hit the button.  See
    # player_core.sdl_hints for the whole mechanism; the satellites have asked
    # for this all along and the main player had not.
    deliver_the_focusing_click()
    pygame.init()
    if args.borderless:
        pos_y, client_h, flags = args.y, args.height, pygame.NOFRAME
    else:
        chrome = get_window_chrome_height()
        pos_y, client_h, flags = (args.y + chrome if args.y is not None else None,
                                  max(1, args.height - chrome), 0)
    if args.x is not None and pos_y is not None:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{args.x},{pos_y}"
    icon = _load_icon_surface()
    if icon is not None:
        pygame.display.set_icon(icon)  # must precede set_mode to take effect
    screen = pygame.display.set_mode((args.width, client_h), flags)
    pygame.display.set_caption("Nau")
    return screen


def _run(args) -> int:
    _set_aumid(args.config, getattr(args, "taskbar_identity", None))
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
    volume_painter = VolumeHudPainter()
    # Whether this window paints at all.  Fun Time gives the main slot's rect to
    # Genau in genau mode and minimizes Nau — minimized, so it keeps its taskbar
    # button — and says so on this channel; see nau.display.
    display = Display(player, _HUD_OVERLAYS)
    heatmap = HeatmapStrip()
    console_hud = ConsolePainter()
    # What Fun Time says about the main slot, and what Genau says it is doing
    # to the device.  Both arrive published; before the first read the console
    # still draws, with the player's own controls and nothing claimed about the
    # room around it.
    console = ConsoleModel()
    # Genau's own readout as it last published it, kept between frames the way
    # the console is: a torn or missing read means "keep what you have", and in
    # Nau there is nothing publishing one at all.
    published: DriveHud | None = None
    # Where the cursor is over the console, so a button can name itself on hover.
    hover: tuple[int, int] | None = None
    loop_thumbs = LoopThumbCapture()
    # What of Genau's publish this video's picture believes: the descent
    # forecasts it is holding, and whether Genau has been seen live here.  Above
    # the status writer's closure below, which publishes the touch it chose.
    drive_gate = DriveGate(session)

    # Every status carries the touch-down the trace chose for the boundary in
    # play, so the arbiter ends Genau's turn where the picture drew it ending.
    status_writer = StatusWriter(
        args.status_file,
        lambda published: status_fields(published, drive_gate.handoff_touch()),
    ) if args.status_file else None
    stop_event = threading.Event()
    # Every control on this HUD asks Fun Time rather than acting; so does
    # the close box.  See nau.dashboard.
    dashboard = Dashboard(args.dashboard_cmd_file)
    # The main player's sound, as Fun Time publishes it.  Nau's own mpv is one
    # of two sinks it drives (Genau's clip audio is the other), so the level
    # here is drawn and reported, never decided; see nau.volume_control.
    volume = VolumeControl(dashboard)
    # A press the console's buttons did not take: the chip, the timeline, or the
    # video.  See nau.pointer.
    pointer = Pointer(session, heatmap, volume)

    # Clip navigation: a clip carved from a compilation records its siblings,
    # order, and source scene in its sidecar (see nau.clip_nav). Built once over
    # the whole discovered library so "compilation"/"full video"/"clip jump" can
    # jump from whatever is on screen.  With no library there is nothing to jump
    # to, and an empty index answers that without a special case.
    entries = source.entries if source is not None else []
    clip_nav = ClipNav.build(
        [e.video for e in entries] + [c.video for c in (source.clips if source else [])],
        source.metadata_root if source is not None else None,
    )
    notices = NoticeWriter(getattr(args, "notice_file", None))
    jumps = ClipJumps(
        clip_nav, session, {e.video: e.funscript for e in entries}, notices,
    )
    # The funscript's own two moves — past this video's quiet stretch, or on to a
    # video that has scripting at all.  They need nothing but the session, since
    # the playlist already carries each video's funscript beside it.
    funscript_jumps = FunscriptJumps(session, notices)
    # Entering a compilation swaps the playlist in memory only, and Fun Time can
    # only rotate its resumed file onto a video the file contains — which a
    # compilation's clips often are not.  So the clip is remembered too, and the
    # volume comes back around it rather than around whatever the list leads with.
    jumps.resume(
        remembered.compilation,
        Path(remembered.video) if remembered.video else None,
    )
    # The length filter, the volume and Fun Time's own narrowing, as the console
    # draws them and the memory keeps them.  See nau.modes.
    modes = Modes(source, session, jumps, remembered=remembered.length_mode)
    # RELOAD_PLAYLIST: Fun Time owns the playlist file when it passes one, and
    # rewrites it whenever the room's selection changes.  Standalone there is
    # nobody writing one, so there is nothing to take up.
    take_up_playlist = partial(
        reload_playlist, session, jumps,
        partial(resolve_playlist, args, source=source)
        if args.playlist is not None else None)

    while not stop_event.is_set():
        win_w, win_h = screen.get_size()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                dashboard.take_quit_gesture(stop_event)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                pressed = console_hud.press_at(*ev.pos)
                if pressed:
                    dashboard.post(pressed)
                else:
                    # A press that missed every button falls through to the video,
                    # where it seeks or pauses as it always did.
                    pointer.press(*ev.pos, win_w=win_w, win_h=win_h)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                console_hud.release()
            elif ev.type == pygame.MOUSEMOTION:
                hover = console_hud.hover_at(*ev.pos)
                if not ev.buttons[0]:
                    # The button came up somewhere this loop never saw it — over
                    # another window, or off the screen — so nothing is held.
                    console_hud.release()
                elif console_hud.holding:
                    # Dragging a bar on the drive readout keeps setting its level,
                    # the way the volume slider below does.  The band a press took
                    # hold of keeps the drag even as the pointer wanders off it,
                    # and says nothing while the level under it has not moved.
                    dragged = console_hud.drag_to(*ev.pos)
                    if dragged:
                        dashboard.post(dragged)
                else:
                    pointer.drag(*ev.pos, win_w=win_w, win_h=win_h)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_q and ev.mod & pygame.KMOD_CTRL:
                    dashboard.take_quit_gesture(stop_event)
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
                    modes.toggle_length()
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
                    reload_playlist=take_up_playlist,
                    toggle_length_mode=modes.toggle_length,
                    set_length_mode=modes.set_length,
                    play_compilation=jumps.play_compilation,
                    play_full_vid=jumps.play_full_vid,
                    play_clip_jump=jumps.play_clip_jump,
                    jump_to_funscript=funscript_jumps.jump_to_funscript,
                    next_funscripted=funscript_jumps.next_funscripted,
                    end_compilation=modes.end_compilation,
                    set_f_mode=modes.set_f_mode,
                    set_volume_hud=volume.set,
                    set_display=display.set_active,
                )

        session.advance()
        if status_writer is not None:
            status_writer.write(session)

        # Write the mode down whenever it moves, whichever path moved it, so the
        # next session — which opens on this one's resumed playlist — can name it
        # and re-enter the volume it was in.  Above the painting, because a
        # blanked Nau still navigates: in genau mode the `[`/`]` keys drive it in
        # the background, and where they leave it is what the next session opens
        # on whether or not anyone was looking.
        mode_now = modes.remembered
        if mode_now != remembered:
            remembered = mode_now
            memory.write(mode_now)

        # Black while Genau owns the main slot's rect, and none of the work below
        # that builds a picture nobody can see.  Everything above still runs:
        # navigation, the funscript, the status file clipper_save reads.
        display.sync(win_w, win_h)
        if not display.active:
            clock.tick(60)
            continue

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

        # The top-left corner: the console — the video's name and the dot saying
        # whether a bare command lands here, what is selecting this playlist, what
        # is driving the device, and every control Fun Time's dashboard used to
        # hold for this slot.  The name heads it now rather than sitting in a chip
        # of its own beneath.
        if args.console_file is not None:
            console = read_console(args.console_file) or console
        if args.drive_file is not None and genau_drives(console.mode):
            published = read_drive(args.drive_file) or published
        drive = drive_gate.readout(published, genau_behind=genau_drives(console.mode))
        left, top = hud_xy()
        panel = console_hud.bgra(ConsoleHud(
            modes=modes.hud,
            # Nau knows its own playback rate; Fun Time does not publish it, so it
            # is folded in here.  The dot's `active` and everything else came down
            # in the console file.
            console=with_playback_speed(console, session.speed),
            drive=drive,
        ), hover=hover)
        player.overlay(_OV_CONSOLE, left, top, panel)

        # The volume control, at the right-hand end of the row above the timeline —
        # beside the transport, where a player's has always been.
        vx, vy = chip_xy(win_w=win_w, win_h=win_h, timeline_h=timeline_height(heatmap))
        player.overlay(_OV_VOLUME, vx, vy, volume_painter.bgra(volume.hud))

        _draw_loop_thumbnails(player, loop_thumbs, session, heatmap, win_w, win_h)

        clock.tick(60)

    session.close()
    pygame.quit()
    return 0
