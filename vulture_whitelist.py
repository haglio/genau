"""Vulture whitelist — false positives consumed by frameworks/APIs."""

# Win32 STARTUPINFO fields consumed by the subprocess module
# (runtime_support.py: hidden_subprocess_kwargs)
_.dwFlags  # type: ignore[name-defined]
_.wShowWindow  # type: ignore[name-defined]

# ctypes PROPVARIANT struct fields consumed by COM IPropertyStore
# (win32.py: _set_lnk_aumid)
_.vt  # type: ignore[name-defined]
_.pwszVal  # type: ignore[name-defined]

# Test infrastructure for production read functions (read_rhcache_all_frames,
# read_rhcache_meta) — the only way to create .rhcache files for tests.
_.write_rhcache  # type: ignore[name-defined]

# VoiceListener.stop() is called externally to signal shutdown
_.stop  # type: ignore[name-defined]

# SDL2 Renderer.draw_color is a property set dynamically for HUD mode
# (pygame_view.py: _present_scene)
_.draw_color  # type: ignore[name-defined]

# libmpv properties set via python-mpv's dynamic attribute API
# (mpv_player.py: MpvPlayer drives pause / A-B loop on the MPV object)
_.pause  # type: ignore[name-defined]
_.ab_loop_a  # type: ignore[name-defined]
_.ab_loop_b  # type: ignore[name-defined]

# MpvPlayer members driven only by the satellite player (satellite/session.py):
# the lock's loop toggle and the prefetch window it rolls as clips auto-advance.
# satellite/ is a package vulture does not scan yet — drop these when it joins
# the dead-code scan.
_.set_loop_file  # type: ignore[name-defined]
_.stage_next  # type: ignore[name-defined]
_.clear_next  # type: ignore[name-defined]
_.advanced_to_next  # type: ignore[name-defined]
_.drop_consumed  # type: ignore[name-defined]
