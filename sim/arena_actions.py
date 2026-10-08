"""Arena action boundaries for one Life Orb cost and settled bonus attribution.

Native multi-hit/area casts and taught multi-target actions share one boundary.
Their direct damage packets receive the item bonus, while retaliation, DOT,
terrain and reaction products remain outside. The self-cost bypasses shields and survival
items and is never credited to an enemy's damage output.
"""
from contextlib import contextmanager

from arena_combinations import _effect, clear as clear_shield
from items import FINISHED


def current(unit):
    return getattr(unit, '_arena_action', None)


@contextmanager
def action(battle, unit, t, move):
    if not battle._arena_on:
        yield None
        return
    previous = current(unit)
    packet = {'move': move, 'benefit': False, 'action_index': None}
    unit._arena_action = packet
    try:
        yield packet
    finally:
        unit._arena_action = previous
        if (getattr(unit, 'item_key', None) == 'life_orb' and packet['benefit']
                and unit.alive):
            from arena_traits import sheer_force_applies
            if not sheer_force_applies(battle, unit, move):
                _recoil(battle, unit, t, packet)


def prepare_hit(battle, source, target, damage, direct, move=None):
    if (not battle._arena_on or not direct or damage <= 0 or not source.alive
            or source.team == target.team or getattr(source, 'item_key', None) != 'life_orb'):
        return damage, None
    # Retaliation remains direct for shields, survival and other traits; only
    # Life Orb rejects it, including action benefit and therefore its self-cost.
    if move is not None and move.get('category') == 'retaliation':
        return damage, None
    spec = FINISHED['life_orb']
    amplified = int(damage * (1. + spec['direct_bonus']))
    return amplified, {'baseline_damage': damage, 'amplified_damage': amplified,
                       'fraction': spec['direct_bonus']}


def settle_hit(battle, source, target, context, trait_context, t, action_index,
               actual_hp, absorbed, hp_before, shield_before, sturdy_before, sash_before):
    if context is None:
        return
    packet = current(source)
    if packet is not None and (actual_hp > 0 or absorbed > 0):
        packet['benefit'] = True
        if packet['action_index'] is None:
            packet['action_index'] = action_index
    from arena_traits import settled_hp
    baseline = context['baseline_damage']
    stage = context['amplified_damage']
    if trait_context:
        stage = trait_context['baseline_damage']
        if trait_context['weakened']:
            baseline = int(baseline * (1. - trait_context['weaken_fraction']))
    survival = sturdy_before or sash_before
    original = settled_hp(baseline, hp_before, shield_before, survival)
    boosted = settled_hp(stage, hp_before, shield_before, survival)
    extra_hp = max(0, boosted - original)
    extra_absorbed = max(0, min(stage, shield_before) - min(baseline, shield_before))
    if extra_hp > 0 or extra_absorbed > 0:
        with _effect(battle, source, target, 'life_orb', 'empowered_hit', t,
                     amount=extra_hp, extra_damage=extra_hp, absorbed=extra_absorbed,
                     baseline_damage=baseline, baseline_actual=original,
                     actual_total=actual_hp, action_index=action_index,
                     fraction=context['fraction'], reason='settled_direct_item_extra'):
            battle._emit_state(source, t)


def _recoil(battle, source, t, packet):
    requested = max(1, int(source.max_hp * FINISHED['life_orb']['recoil_fraction']))
    amount = min(max(0, source.hp), requested)
    if amount <= 0:
        return
    move = packet['move']
    with _effect(battle, source, source, 'life_orb', 'damage', t,
                 amount=amount, requested=requested, recoil=True,
                 damage_scope='self_cost', action_index=packet['action_index'],
                 move_name=move['name'] if move else None,
                 reason='life_orb_recoil'):
        source.hp -= amount
        source.self_damage += amount
        if not source.alive:
            source.hp = 0
            clear_shield(source)
            from arena_interactions import clear
            clear(source)
            if source.idx not in battle._dead:
                battle._dead.add(source.idx)
                battle.events.append((t, 'die', source.idx))
        battle._emit_state(source, t)
