"""Both players must ask SDL for the click that focuses their window.

Neither player is ever the focused window — Fun Time places both with
SWP_NOACTIVATE — so the click that lands on a console button is also the click
that focuses the window, and SDL drops that one unless
``player_core.sdl_hints.deliver_the_focusing_click`` has run.  Without it every
press on the console has to be made twice, which is what the main player did for
months while the satellites did not.

Read off the source rather than exercised: neither window-opening path can run in
a unit test — each needs a real window and the libmpv DLL — and the files are
read by path rather than imported, because importing either one at collection
time leaves pygame and the view module bound in a way the tests that patch them
then see through.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WINDOW_OPENERS = (REPO / "genau" / "pygame_view.py", REPO / "nau" / "app.py")


def _call_lines(source: Path) -> tuple[list[int], list[int]]:
    """(lines calling deliver_the_focusing_click, lines calling pygame.init)."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    hint: list[int] = []
    init: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name) and target.id == "deliver_the_focusing_click":
            hint.append(node.lineno)
        elif (isinstance(target, ast.Attribute) and target.attr == "init"
                and isinstance(target.value, ast.Name) and target.value.id == "pygame"):
            init.append(node.lineno)
    return hint, init


@pytest.mark.parametrize("source", WINDOW_OPENERS, ids=lambda p: p.name)
def test_the_focusing_click_is_asked_for_before_the_window_exists(source: Path):
    """SDL reads the hint when the click arrives, but the window must not have
    been created first — so the call comes before ``pygame.init()``."""
    hint, init = _call_lines(source)

    assert hint, f"{source.name} never calls deliver_the_focusing_click"
    assert init, f"{source.name} no longer calls pygame.init — move this guard"
    assert max(hint) < min(init), (
        f"{source.name} asks for the focusing click after its window exists"
    )
