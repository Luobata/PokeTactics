"""Opt-in base-stat budget: BST gives shape, never extra points within a tier.

All six axes, including speed, spend from the same integer pool. Each is bounded
to 60–160% of the tier's equal share. HP costs one point per two hit points; the
other five axes cost one each. Thus max_hp/2 + atk + def + spa + spd + speed is
exactly the tier budget before team synergies and equipment. Profile HP/attack
interval multipliers must NOT be applied afterward in budget_v1; profile range
and movement remain tactical identity. Existing tier prices are left intact.

This conserves a transparent base budget, not effective DPS or winning chances:
move power, typing, range, abilities and synergies still require balance trials.
"""

import math
from data import ATTACK_INTERVAL_MULT, SPEED_TO_ATTACK_INTERVAL, pokedex

STAT_KEYS = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")
BUDGET_BY_TIER = {1: 300, 2: 420, 3: 540}
MIN_SHARE, MAX_SHARE = 0.60, 1.60


def normalize(base, tier):
    """Proportionally allocate and round an exact fixed pool under hard caps."""
    if type(tier) is not int or tier not in BUDGET_BY_TIER:
        raise ValueError("budget_v1 supports tiers 1, 2 and 3")
    values = [base[key] for key in STAT_KEYS]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("six positive finite base stats are required")
    budget = BUDGET_BY_TIER[tier]
    low, high = int(budget / 6 * MIN_SHARE), int(budget / 6 * MAX_SHARE)
    # Clamped proportional water filling. Bisection also handles multiple caps.
    left, right = 0.0, budget / min(values)
    for _ in range(80):
        factor = (left + right) / 2
        if sum(min(high, max(low, value * factor)) for value in values) < budget:
            left = factor
        else:
            right = factor
    raw = [min(high, max(low, value * (left + right) / 2)) for value in values]
    points = [math.floor(value) for value in raw]
    remaining = budget - sum(points)
    order = sorted(range(6), key=lambda i: (-(raw[i] - points[i]), i))
    for index in order:
        if remaining and points[index] < high:
            points[index] += 1
            remaining -= 1
    if remaining:
        raise ArithmeticError("stat allocation failed to conserve its budget")
    return dict(zip(STAT_KEYS, points))


def allocation(species_id, tier):
    return normalize(pokedex().species_record(species_id)["base"], tier)


def unit_stats(piece):
    points = allocation(piece.species_id, piece.tier)
    return {"max_hp": 2 * points["hp"], "attack": points["attack"],
            "defense": points["defense"], "sp_attack": points["special_attack"],
            "sp_defense": points["special_defense"], "speed": points["speed"],
            "attack_interval": SPEED_TO_ATTACK_INTERVAL(points["speed"])
                               * ATTACK_INTERVAL_MULT,
            "points": points, "budget": BUDGET_BY_TIER[piece.tier]}
