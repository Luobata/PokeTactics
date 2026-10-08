"""Bounded arena interactions triggered by settled native, shield and move facts.

No random rolls or recursive actions. Health loss and healing are authoritative;
shield consumption is distinct from both. Classic battles never call these hooks.
"""
from contextlib import contextmanager
from data import ENERGY_MAX
from items import FINISHED
from arena import AUGMENTS

EPS = 1e-9


@contextmanager
def _effect(battle, caster, target, key, effect, t, cast_index=None, **details):
    payload = {'cast_index': cast_index, 'event_count': 0,
               'source_pos': caster.pos, 'caster_pos': caster.pos,
               'target_pos': target.pos, **details}
    marker = len(battle.events)
    battle.events.append((t, 'combo_effect', caster.idx, target.idx, key, effect, payload))
    yield payload
    payload['event_count'] = len(battle.events) - marker - 1


def _ready(unit, key, t, cooldown, limit=None):
    return (unit.alive and t + EPS >= unit.combo_ready_at.get(key, 0.)
            and (limit is None or unit.combo_uses.get(key, 0) < limit))


def _used(unit, key, t, cooldown):
    unit.combo_uses[key] = unit.combo_uses.get(key, 0) + 1
    unit.combo_ready_at[key] = t + cooldown


def _energy(battle, caster, target, key, t, cast_index, reason):
    gained = max(0, min(8, ENERGY_MAX - target.energy))
    if not gained or not target.alive:
        return False
    with _effect(battle, caster, target, key, 'energy', t, cast_index,
                 amount=gained, requested=8, reason=reason):
        target.energy += gained
        battle._emit_state(target, t)
    return True


def clear(unit):
    unit.shield = 0
    unit.shield_until = 0.
    unit.shield_source_idx = None
    unit.shield_cast_index = None
    unit.shield_source_key = None
    unit.shield_source_kind = None
    unit.shield_id = None
    unit.shield_cycle_absorbed = 0
    unit.shield_feedback_absorbed = 0
    unit.shield_feedback_used = False
    unit.shield_ward_used = False


def _start_shield_cycle(battle, patient):
    battle._next_shield_id = getattr(battle, '_next_shield_id', 0) + 1
    patient.shield_id = battle._next_shield_id
    patient.shield_cycle_absorbed = 0
    patient.shield_feedback_absorbed = 0
    patient.shield_feedback_used = False
    patient.shield_ward_used = False


def _expiry_packet(unit, t):
    if not unit.shield or t + EPS < unit.shield_until:
        return None
    packet = (unit.shield_source_idx, 'expire', {
        'amount': unit.shield, 'shield': 0, 'duration': 0.,
        'expires_at': unit.shield_until, 'cast_index': None,
        'source_cast_index': unit.shield_cast_index, 'shield_id': unit.shield_id,
        'source_key': getattr(unit, 'shield_source_key', None) or 'heart_bell',
        'source_kind': getattr(unit, 'shield_source_kind', None) or 'combo',
        'reason': 'duration_elapsed'})
    clear(unit)
    return packet


def emit_packets(battle, target, t, packets):
    for source, effect, payload in packets:
        caster = battle.units[source] if source is not None else target
        if payload.get('source_kind') == 'native':
            # Native shields retain their originating skill, while the incoming
            # damage index is kept separately for reaction-time presentation.
            details = {**payload, 'action_index': payload.get('cast_index')}
            details['cast_index'] = payload.get('source_cast_index')
            with battle._skill_effect(caster, target, effect, t, **details):
                battle._emit_state(target, t)
        else:
            with _effect(battle, caster, target, payload.get('source_key', 'heart_bell'),
                         effect, t, **payload):
                battle._emit_state(target, t)
        if effect == 'absorb':
            after_absorb(battle, caster, target, t, payload)


def can_shield(patient, amount, t):
    """One finite shield slot; equal/weaker effects cannot refresh ownership."""
    current = patient.shield if patient.shield_until > t + EPS else 0
    return patient.alive and amount > max(0, current)


def grant_shield(battle, caster, patient, amount, t, cast_index, *,
                 source_kind='native', source_key=None, reason='native_protection',
                 **extra_details):
    """Use the same absorption ledger for native and item-created shields."""
    if not battle._arena_on or not patient.alive:
        return False
    amount = max(0, int(amount))
    expire(battle, patient, t)
    if not can_shield(patient, amount, t):
        return False
    source_key = source_key or caster.ult_arch
    if not patient.shield or patient.shield_id is None:
        _start_shield_cycle(battle, patient)
    elif patient.shield_source_idx != caster.idx:
        # Count only this caster's absorption for feedback. Neither bridge's
        # once-per-cycle flag is reset when an active shield changes owners.
        patient.shield_feedback_absorbed = 0
    details = dict(amount=max(0, amount - patient.shield), requested=amount,
                   shield=amount, duration=3., expires_at=t + 3., reason=reason,
                   source_kind=source_kind, source_key=source_key,
                   shield_id=patient.shield_id, **extra_details)
    context = (battle._skill_effect(caster, patient, 'shield', t, cast_index, **details)
               if source_kind == 'native' else
               _effect(battle, caster, patient, source_key, 'shield', t, cast_index, **details))
    with context:
        patient.shield = amount
        patient.shield_until = t + 3.
        patient.shield_source_idx = caster.idx
        patient.shield_cast_index = cast_index
        patient.shield_source_key = source_key
        patient.shield_source_kind = source_kind
        battle._emit_state(patient, t)
    return True


def expire(battle, unit, t):
    if not battle._arena_on:
        return
    packet = _expiry_packet(unit, t)
    if packet is not None:
        emit_packets(battle, unit, t, [packet])


def consume(battle, target, damage, t, action_index=None, attacker_idx=None):
    """Consume silently; caller emits its damage event before these annotations.

    This preserves the original absolute cast index even when a hit expires or
    consumes a shield. DOT uses the same path without becoming a native action.
    """
    packets = []
    packet = _expiry_packet(target, t)
    if packet is not None:
        packets.append(packet)
    absorbed = min(max(0, damage), target.shield) if target.alive else 0
    if absorbed:
        source, source_cast = target.shield_source_idx, target.shield_cast_index
        source_key = getattr(target, 'shield_source_key', None) or 'heart_bell'
        source_kind = getattr(target, 'shield_source_kind', None) or 'combo'
        until = target.shield_until
        if target.shield_id is None:
            _start_shield_cycle(battle, target)
        target.shield -= absorbed
        target.shield_absorbed += absorbed
        target.shield_cycle_absorbed += absorbed
        target.shield_feedback_absorbed += absorbed
        packets.append((source, 'absorb', {
            'amount': absorbed, 'shield': target.shield, 'expires_at': until,
            'cast_index': action_index, 'source_cast_index': source_cast,
            'source_key': source_key, 'source_kind': source_kind,
            'shield_id': target.shield_id, 'cycle_absorbed': target.shield_cycle_absorbed,
            'source_absorbed': target.shield_feedback_absorbed,
            'feedback_used': target.shield_feedback_used,
            'ward_used': target.shield_ward_used,
            'attacker_idx': attacker_idx, 'reason': 'damage_absorbed'}))
        if not target.shield:
            clear(target)
    return max(0, damage - absorbed), packets


def after_absorb(battle, caster, patient, t, packet):
    """Read the original shield ledger even when the slot was consumed/cleared."""
    if not battle._arena_on or packet['amount'] <= 0:
        return
    key = 'ward_bracer'
    spec = FINISHED[key]
    threshold = patient.max_hp * spec['shield_threshold']
    if (getattr(patient, 'item_key', None) == key and not packet['ward_used']
            and packet['cycle_absorbed'] + EPS >= threshold
            and _ready(patient, key, t, spec['cooldown'], spec['limit'])):
        with _effect(battle, patient, patient, key, 'charge', t,
                     action_index=packet['cast_index'],
                     source_cast_index=packet['source_cast_index'],
                     shield_id=packet['shield_id'], threshold=threshold,
                     absorbed=packet['cycle_absorbed'], amount=0,
                     fraction=spec['basic_bonus'], duration=spec['charge_duration'],
                     expires_at=t + spec['charge_duration'],
                     reason='effective_shield_absorption'):
            patient.ward_charge_until = t + spec['charge_duration']
            patient.ward_charge_context = {
                'shield_id': packet['shield_id'],
                'source_cast_index': packet['source_cast_index']}
            _used(patient, key, t, spec['cooldown'])
            if patient.shield_id == packet['shield_id']:
                patient.shield_ward_used = True
            battle._emit_state(patient, t)

    key = 'barrier_feedback'
    spec = AUGMENTS[key]
    threshold = patient.max_hp * spec['shield_threshold']
    # The protected unit is the trigger origin; the original caster owns the
    # cooldown and cap across every allied shield, including item-created ones.
    if (caster is patient or caster.team != patient.team
            or key not in battle.arena_teams[caster.team] or packet['feedback_used']
            or packet['source_absorbed'] + EPS < threshold
            or not _ready(caster, key, t, spec['cooldown'], spec['limit'])):
        return
    gained = max(0, min(spec['energy'], ENERGY_MAX - caster.energy))
    if not gained:
        return
    with _effect(battle, patient, caster, key, 'energy', t,
                 action_index=packet['cast_index'],
                 source_cast_index=packet['source_cast_index'], source_idx=caster.idx,
                 shield_id=packet['shield_id'], threshold=threshold,
                 absorbed=packet['source_absorbed'], amount=gained,
                 requested=spec['energy'], reason='allied_shield_absorption'):
        caster.energy += gained
        _used(caster, key, t, spec['cooldown'])
        if patient.shield_id == packet['shield_id']:
            patient.shield_feedback_used = True
        battle._emit_state(caster, t)


def prepare_basic(battle, unit, target, damage, t):
    """Enhance one successful basic packet; retain its unenhanced settlement."""
    key = 'ward_bracer'
    if (not battle._arena_on or getattr(unit, 'item_key', None) != key
            or not unit.alive or not target.alive or damage <= 0
            or t + EPS >= unit.ward_charge_until):
        return damage, None
    extra = max(0, int(damage * FINISHED[key]['basic_bonus']))
    if not extra:
        return damage, None
    shield = target.shield if target.shield_until > t + EPS else 0
    baseline_actual = min(target.hp, max(0, damage - shield))
    if (baseline_actual >= target.hp and target.item_sash and not target.item_sash_used):
        baseline_actual = max(0, target.hp - 1)
    enhancement = {
        **(unit.ward_charge_context or {}), 'requested': extra,
        'baseline_damage': damage, 'baseline_actual': baseline_actual,
        'damage_taken_before': target.damage_taken,
        'shield_absorbed_before': target.shield_absorbed,
        'baseline_absorbed': min(damage, shield)}
    unit.ward_charge_until = 0.
    unit.ward_charge_context = None
    return damage + extra, enhancement


def settle_basic(battle, unit, target, t, action_index, enhancement):
    """Credit only the extra real HP/absorption, never emit another attack."""
    if enhancement is None:
        return
    actual = enhancement.get('settled_actual',
                             max(0, target.damage_taken - enhancement['damage_taken_before']))
    settled_absorbed = enhancement.get('settled_absorbed',
                                      target.shield_absorbed - enhancement['shield_absorbed_before'])
    ward_actual = min(actual, enhancement.get('settled_ward_actual', actual))
    ward_absorbed = min(settled_absorbed, enhancement.get('settled_ward_absorbed', settled_absorbed))
    absorbed = max(0, ward_absorbed - enhancement['baseline_absorbed'])
    extra = max(0, ward_actual - enhancement['baseline_actual'])
    with _effect(battle, unit, target, 'ward_bracer', 'empowered_basic', t,
                 action_index=action_index, amount=extra, extra_damage=extra,
                 absorbed=absorbed, actual_total=actual,
                 requested=enhancement['requested'],
                 baseline_damage=enhancement['baseline_damage'],
                 baseline_actual=enhancement['baseline_actual'],
                 shield_id=enhancement.get('shield_id'),
                 source_cast_index=enhancement.get('source_cast_index'),
                 reason='charged_successful_basic'):
        battle._emit_state(unit, t)


def after_cleanse(battle, unit, patient, kind, t, cast_index):
    """Only a successful native major-status removal from another ally."""
    key = 'clarity_charm'
    spec = FINISHED[key]
    native = (isinstance(cast_index, int) and 0 <= cast_index < len(battle.events)
              and battle.events[cast_index][1:3] == ('cast', unit.idx)
              and battle.events[cast_index][4] == 'arena_' + unit.ult_arch)
    if (not battle._arena_on or not native or patient is unit
            or patient.team != unit.team or not patient.alive
            or getattr(unit, 'item_key', None) != key
            or not _ready(unit, key, t, spec['cooldown'], spec['limit'])):
        return False
    if grant_shield(battle, unit, patient, int(patient.max_hp * spec['shield_fraction']),
                    t, cast_index, source_kind='combo', source_key=key,
                    reason='native_other_major_cleanse', cleansed_status=kind):
        _used(unit, key, t, spec['cooldown'])
        return True
    return False


def after_knockback(battle, unit, target, origin, t, cast_index, action_index):
    """A surviving enemy's completed forced move opens the next attack window."""
    key = 'breach_momentum'
    spec = AUGMENTS[key]
    if (not battle._arena_on or unit is None or unit.team == target.team
            or origin == target.pos or not target.alive
            or key not in battle.arena_teams[unit.team]
            or not _ready(unit, key, t, spec['cooldown'], spec['limit'])):
        return False
    with _effect(battle, unit, target, key, 'vulnerability', t, cast_index,
                 action_index=action_index, fraction=spec['vulnerability'],
                 duration=spec['duration'], expires_at=t + spec['duration'],
                 origin=origin, destination=target.pos,
                 reason='successful_enemy_knockback'):
        target.vulnerable_until = t + spec['duration']
        target.vulnerability_source = unit.idx
        _used(unit, key, t, spec['cooldown'])
        battle._emit_state(target, t)
    return True


def _shield(battle, caster, patient, t, cast_index):
    amount = min(int(patient.max_hp * .08), int(patient.max_hp * .15))
    return grant_shield(battle, caster, patient, amount, t, cast_index,
                        source_kind='combo', source_key='heart_bell',
                        reason='native_other_heal_at_least_5_percent')


def after_native(battle, unit, target, t, cast_index, already_poisoned,
                 lost_hp, heals):
    """heals contains (patient, actual HP restored), only from this native cast."""
    if not battle._arena_on or not unit.alive:
        return
    augments = battle.arena_teams[unit.team]
    if ('poison_catalyst' in augments and already_poisoned and lost_hp > 0
            and _ready(unit, 'poison_catalyst', t, 2., 3)
            and _energy(battle, unit, unit, 'poison_catalyst', t, cast_index,
                        'native_primary_hit_preexisting_poison')):
        _used(unit, 'poison_catalyst', t, 2.)

    other_heals = [(patient, actual) for patient, actual in heals
                   if patient is not unit and patient.alive and actual > 0]
    from arena_bonds import after_native_support
    for patient, actual in other_heals:
        after_native_support(battle, unit, patient, actual, 'heal', t, cast_index)
    if (getattr(unit, 'item_key', None) == 'heart_bell'
            and _ready(unit, 'heart_bell', t, 4.)):
        for patient, actual in other_heals:
            if actual + EPS >= patient.max_hp * .05 and _shield(battle, unit, patient, t, cast_index):
                _used(unit, 'heart_bell', t, 4.)
                break
    if ('watch_echo' not in augments or unit.arena_role != 'support'
            or not other_heals or not _ready(unit, 'watch_echo', t, 4., 3)):
        return
    candidates = [friend for friend in battle.units
                  if friend is not unit and friend.alive and friend.team == unit.team
                  and friend.arena_role == 'attack' and friend.energy < ENERGY_MAX
                  and abs(friend.pos[0] - unit.pos[0]) + abs(friend.pos[1] - unit.pos[1]) <= 2]
    recipient = min(candidates, key=lambda friend: (-friend.energy, battle._target_key(unit, friend)),
                    default=None)
    if recipient is not None and _energy(battle, unit, recipient, 'watch_echo', t, cast_index,
                                        'support_native_other_effective_heal'):
        _used(unit, 'watch_echo', t, 4.)
