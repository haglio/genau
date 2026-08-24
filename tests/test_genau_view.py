from __future__ import annotations


def test_pygame_view_creates_window_and_renderer(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=1200, height=900, x=10, y=20, title="Genau")

    assert view.width == 1200
    assert view.height == 900
    mock_pygame.init.assert_called_once()


def test_pygame_view_get_size_delegates_to_window(mock_pygame):
    from genau.pygame_view import PygameView

    view = PygameView(width=800, height=600)
    view.window.size = (800, 600)

    assert view.get_size() == (800, 600)
