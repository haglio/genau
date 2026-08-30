"""Vulture whitelist — false positives consumed by frameworks/APIs."""

# ctypes PROPVARIANT struct fields consumed by COM IPropertyStore
# (win32.py: _set_lnk_aumid)
_.vt  # type: ignore[name-defined]
_.pwszVal  # type: ignore[name-defined]

# SDL2 Renderer.draw_color is a property set dynamically for HUD mode
# (pygame_view.py: _present_scene)
_.draw_color  # type: ignore[name-defined]

# genau_vr.vr_runtime's answer to "did the loader bind?", read by
# tests/test_gvr_without_openxr.py — which vulture does not scan, so it cannot
# see either reader.
WINREG_AVAILABLE  # type: ignore[name-defined]
OPENXR_AVAILABLE  # type: ignore[name-defined]

# tools.inventory's "which written-down tests stopped being collected", read by
# tests/test_inventory.py and by tools/update_inventory.py's --accept-removals
# path.  The scan below covers tools/ on its own, and vulture cannot be pointed
# at tests/ to see the caller -- the suite's fakes stand in for protocols and
# would drown the gate in false positives.
missing_from  # type: ignore[name-defined]
