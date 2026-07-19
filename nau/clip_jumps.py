"""The playlist moves a clip's sidecar makes possible.

:mod:`nau.clip_nav` reads the ``clip`` metadata Evolver records and answers
questions about one video; this drives the playlist from those answers, which is
what Fun Time's "compilation" / "full video" / "money shot" actually do.

They lived as three closures inside the run loop, where nothing could reach them
to test and the one piece of state they own had nowhere to live: playing a
compilation replaces the whole playlist, so it is a place you can be *stuck* —
unlike the other two, which move to one video and leave the playlist alone.  That
is the state Nau's HUD reports, so it belongs with whatever puts you in it.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ClipJumps:
    """Fun Time's three clip navigations, over one session's playlist."""

    def __init__(self, nav, session, funscripts: dict[Path, Path | None], notices) -> None:
        self._nav = nav
        self._session = session
        self._funscripts = funscripts
        self._notices = notices
        self._compilation = ""

    @property
    def compilation(self) -> str:
        """The compilation whose clips are the playlist, or "" while browsing."""
        return self._compilation

    def resume(self, compilation: str) -> None:
        """Rebuild *compilation* around the clip Nau opened on, when it is one.

        Entering a compilation swaps the playlist in memory only — the file Fun
        Time resumes never sees it — so reopening lands on the ordinary browse
        rotated to the clip that was on screen, and the volume has to be built
        again for "next" to walk it.  The clip has to belong to the remembered
        volume: Fun Time can rebuild rather than resume, and then that volume
        belongs to a session that is over.
        """
        current = self._session.current_video
        if not compilation or self._nav.compilation_of(current) != compilation:
            return
        self._enter(current)

    def leave_compilation(self) -> None:
        """Note that the playlist was rebuilt from somewhere else — the library's
        length modes and Fun Time's reload both do that, and either way the volume
        is no longer what is on screen."""
        self._compilation = ""

    def end_compilation(self, playlist: list[tuple[Path, Path | None]]) -> None:
        """Leave the volume for *playlist*, without interrupting the video.

        Leaving is about what "next" will reach, not about what is playing, so
        the clip on screen carries on — it is simply no longer surrounded by its
        siblings.  (Naming a length mode is the other way out, and that one does
        land on the new mode's content, which is the point of asking for it.)
        """
        if not self._compilation:
            return
        self._compilation = ""
        self._session.replace_playlist(playlist)

    def play_compilation(self) -> None:
        """Reorder the playlist to just the current clip's compilation, in order."""
        current = self._session.current_video
        if not self._enter(current):
            self._notices.say("not a compilation clip")
            return
        self._notices.say(
            f"compilation: {len(self._session.playlist)} clips", level="notice")

    def _enter(self, current: Path) -> bool:
        """Put *current*'s compilation in the playlist around it, if it has one.

        The clip on screen keeps playing: it survives into the new list, so the
        session follows it rather than restarting at the volume's first clip.
        """
        siblings = self._nav.compilation_playlist(current)
        if not siblings:
            return False
        self._session.replace_playlist(
            [(video, self._funscripts.get(video)) for video in siblings]
        )
        self._compilation = self._nav.compilation_of(current)
        return True

    def play_full_vid(self) -> None:
        """Jump from the current clip to the library scene it was taken from."""
        self._jump(self._nav.full_vid_of(self._session.current_video), "full video")

    def play_money_shot(self) -> None:
        """Jump from the current full scene to its clip (the reverse of full vid)."""
        self._jump(self._nav.clip_of(self._session.current_video), "money shot")

    def _jump(self, target: Path | None, what: str) -> None:
        """Play *target*, or say *what* had nowhere to go.

        A miss is the common case, not an error: most clips' source movies are not
        in the library at all, so the notice is the whole answer.
        """
        if target is None:
            logger.info("%s: nothing matches %s", what, self._session.current_video.name)
            self._notices.say(f"{what} not available")
            return
        self._session.play_file(target, self._funscripts.get(target))
        self._notices.say(what, level="notice")
