"""Small expedition-only tactical corrections, separate from the legacy roster.

The native move id/name/type and status remain intact. This is a combat payload
override, not an edit to Pokémon learnsets. Gengar pays for special attack in
budget_v1 but its sole old Ghost move otherwise spends 80 energy on 20 physical
power. Give its disruption cast useful damage without removing Normal immunity
or increasing its bounded energy steal. No HP, stat budgets or healing change.
"""
import skills

GENGAR_CAST_POWER = 65
FOCUS_LENS_START_ENERGY = 40


def resolve_cast(piece, stat_mode="legacy"):
    move = skills.resolve_cast(piece)
    if (move is not None and stat_mode == "budget_v1"
            and piece.species_id == 94 and skills.arch_of(94) == "energy_drain"):
        return {**move, "power": GENGAR_CAST_POWER, "damage_stat": "best"}
    return move


def energy_targeting(piece, stat_mode="legacy"):
    """Only Gengar's budget-mode cast targets highest energy within its range."""
    return (stat_mode == "budget_v1" and piece.species_id == 94
            and skills.arch_of(94) == "energy_drain")


def item_description(item_key, stat_mode="legacy"):
    """Mode-specific UI override; None means use the ordinary item description."""
    if stat_mode == "budget_v1" and item_key == "focus_lens":
        return "开场获得40能量；不再提供大招伤害加成。提前启动与持续输出之间的取舍。"
    return None


def apply_item_rules(unit, item_key):
    """After normal equipment, trade the expedition lens's damage for startup."""
    if unit.stat_mode == "budget_v1" and item_key == "focus_lens":
        unit.energy = FOCUS_LENS_START_ENERGY
        unit.item_ult_dmg = 0.0
