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
