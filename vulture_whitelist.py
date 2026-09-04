"""Vulture whitelist — false positives consumed by frameworks/APIs."""

# SDL2 Renderer.draw_color is a property set dynamically for HUD mode
# (pygame_view.py: _present_scene), and Window.position is the property the
# window is placed through (pygame_view.py: PygameView.__init__).
_.draw_color  # type: ignore[name-defined]
_.position  # type: ignore[name-defined]
