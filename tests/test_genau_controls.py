"""The registry's own rules — the ones no single control's test would catch."""
from __future__ import annotations

import pytest

from genau.controls import CONTROLS, VERBS, Control, GenauControls, Verb, _bind
from genau.engine import PlaybackEngine
from player_core.direct_control import DirectControlState


def _controls(**fields) -> GenauControls:
    return GenauControls(
        engine=PlaybackEngine(phase=0.0, last_tick=0.0),
        rh_paused={"value": False},
        step_clip=lambda _step: None,
        **fields,
    )


def _moved(_controls_arg, _value) -> bool:
    return True


class TestOneVerbHasOneOwner:
    def test_two_controls_cannot_claim_the_same_spelling(self):
        """The loser would go silently unreachable, which is the drift the
        registry exists to stop."""
        clash = (
            Control(name="one", verbs=(Verb("EXAMPLE_VERB", _moved),)),
            Control(name="two", verbs=(Verb("EXAMPLE_VERB", _moved),)),
        )

        with pytest.raises(ValueError) as refused:
            _bind(clash)

        assert "EXAMPLE_VERB" in str(refused.value)
        assert "one" in str(refused.value) and "two" in str(refused.value)

    def test_the_registry_that_ships_binds(self):
        assert set(VERBS) == {
            verb.spelling for control in CONTROLS for verb in control.verbs
        }

    def test_every_verb_names_the_control_that_owns_it(self):
        for spelling, (control, verb) in VERBS.items():
            assert verb.spelling == spelling
            assert verb in control.verbs


class TestAControlSaysWhatItCannotActWithout:
    def test_a_control_needing_nothing_can_always_act(self):
        assert Control(name="free", verbs=()).can_act(_controls()) is True

    def test_a_need_this_build_did_not_wire_stops_the_control(self):
        needy = Control(name="needy", verbs=(), needs=("direct_state",))

        assert needy.can_act(_controls()) is False
        assert needy.can_act(_controls(direct_state=DirectControlState())) is True

    def test_every_need_names_a_field_that_exists(self):
        """A misspelled need would read as absent and silence the control."""
        fields = set(GenauControls.__dataclass_fields__)

        for control in CONTROLS:
            assert set(control.needs) <= fields, control.name


class TestHalfACommandIsNotACommand:
    """The arity is part of the spelling, and both halves of the rule matter."""

    @pytest.mark.parametrize("spelling", ["SPEED", "AMP", "CENTER"])
    def test_a_verb_that_wants_a_value_says_so(self, spelling):
        assert VERBS[spelling][1].takes_a_value is True

    @pytest.mark.parametrize(
        "spelling", ["SPEED_UP", "SPEED_DOWN", "CYCLE_SHAPE", "CYCLE_SHAPE_PREV"],
    )
    def test_a_verb_that_stands_alone_says_so(self, spelling):
        assert VERBS[spelling][1].takes_a_value is False
