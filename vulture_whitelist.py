"""Vulture whitelist — false positives consumed by frameworks/APIs."""

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
