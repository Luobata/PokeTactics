"""Versioned table pacing for the tactical expedition Session.

The legacy table simulator keeps ``economy.loss_damage`` unchanged.  This module
gives an explicit opt-in point for a newer tactical ruleset without changing old
replays or embedding a mutable tuning knob in saved games.
"""
from dataclasses import dataclass

import economy


LEGACY_RULESETS = frozenset({
    "base_v1",
    "tactics_v1",
    "tactics_v2",
    "tactics_v3",
})
NATURAL_END_RULESET = "tactics_v4"
KNOWN_RULESETS = LEGACY_RULESETS | {NATURAL_END_RULESET}

NATURAL_CHAMPION = "natural_champion"
FORCED_RANKING = "forced_ranking"
INVALID_ENDING = "invalid_ending"


@dataclass(frozen=True)
class PressurePolicy:
    """A bounded late-game loser-damage policy.

    Exactly one pressure transformation may be set.  ``minimum_loss`` targets
    low-survivor stalemates; ``survivor_factor`` scales the existing coefficient.
    Neither changes damage before ``start_round``.
    """
    start_round: int
    minimum_loss: int | None = None
    survivor_factor: int | None = None

    def __post_init__(self):
        integer_fields = ("start_round",)
        optional_fields = ("minimum_loss", "survivor_factor")
        for field in integer_fields:
            value = getattr(self, field)
            if type(value) is not int or value < 2:
                raise ValueError(f"{field} must be an integer >= 2")
        set_fields = sum(getattr(self, field) is not None for field in optional_fields)
        if set_fields != 1:
            raise ValueError("exactly one pressure field must be set")
        for field in optional_fields:
            value = getattr(self, field)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{field} must be a positive integer")

    def applies(self, round_no: int) -> bool:
        return type(round_no) is int and round_no >= self.start_round

    def loss_damage(self, round_no: int, enemy_survivors: int) -> int:
        legacy = economy.loss_damage(round_no, enemy_survivors)
        if not self.applies(round_no):
            return legacy
        if self.minimum_loss is not None:
            return max(legacy, self.minimum_loss)
        return economy.LOSS_BASE + max(0, enemy_survivors) * self.survivor_factor


LEGACY_POLICY = PressurePolicy(start_round=2**63 - 1, minimum_loss=1)
DEFAULT_NATURAL_END_POLICY = PressurePolicy(start_round=20, minimum_loss=21)


def validate_ruleset(value):
    if not isinstance(value, str) or value not in KNOWN_RULESETS:
        raise ValueError("unknown pacing ruleset")
    return value


def enabled(value):
    return validate_ruleset(value) == NATURAL_END_RULESET


def policy_for(value):
    return DEFAULT_NATURAL_END_POLICY if enabled(value) else LEGACY_POLICY


def loss_damage(value, round_no, enemy_survivors, policy=None):
    """Return deterministic loser damage for an explicit tactical ruleset.

    ``policy`` is an explicit experiment override.  Production callers must omit
    it, so a saved game derives its behavior solely from its immutable ruleset.
    """
    validate_ruleset(value)
    selected = policy_for(value) if policy is None else policy
    if not isinstance(selected, PressurePolicy):
        raise TypeError("policy must be a PressurePolicy")
    # Experimental controls can disable pressure on the candidate ruleset.
    if policy is not None and not enabled(value) and selected is not LEGACY_POLICY:
        raise ValueError("a pressure override requires the natural-ending ruleset")
    return selected.loss_damage(round_no, enemy_survivors)


def ending_kind(alive_count, round_no, max_rounds):
    """Classify a terminal table without treating zero survivors as a champion."""
    if type(alive_count) is not int or type(round_no) is not int or type(max_rounds) is not int:
        raise TypeError("ending counts and rounds must be integers")
    if alive_count == 1:
        return NATURAL_CHAMPION
    if alive_count > 1 and round_no == max_rounds:
        return FORCED_RANKING
    return INVALID_ENDING
