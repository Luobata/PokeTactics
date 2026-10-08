"""Arena offense routes react to real DOT, basic and native-energy facts.

No extra damage packets, RNG rolls, persistent stat mutations or recursive
casts. Item counters and timed bonuses exist only on this battle's units.
"""
from arena import AUGMENTS
from arena_bonds import TACTICS
from arena_combinations import EPS, _effect, _ready, _used
from items import FINISHED
import status


def _tempo_spec(unit):
    tier = getattr(unit, 'bond_tiers', {}).get('bond_combo', 0)
    base = TACTICS['bond_combo']['tiers'].get(tier, {}).get('speed_per_stack', 0.)
    item = (FINISHED['metronome']['speed_per_stack']
            if getattr(unit, 'item_key', None) == 'metronome' else 0.)
    key = 'metronome' if item else 'bond_combo' if base else None
    return key, tier, base, item


def _reset_tempo(battle, unit, t, reason):
    previous, until = unit.tempo_stacks, unit.tempo_until
    if not previous:
        return False
    key, tier, base, item = _tempo_spec(unit)
    with _effect(battle, unit, unit, key, 'expire', t,
                 amount=0, stacks=0, previous_stacks=previous, gained=0,
                 fraction=0., base_fraction=base * previous,
                 item_fraction=item * previous, bond_tier=tier,
                 expires_at=until, duration=0., action_index=None, reason=reason):
        unit.tempo_stacks, unit.tempo_until, unit.tempo_target_idx = 0, 0., None
        battle._emit_state(unit, t)
    return True


def expire(battle, unit, t):
    if not battle._arena_on:
        return
    if unit.tempo_stacks and t + EPS >= unit.tempo_until:
        _reset_tempo(battle, unit, t, 'idle')
    # The stronger augment and the basic bond own separate windows. Expiring
    # either must not erase, shorten or refresh the other one.
    for key, prefix in (('native_inspiration', 'offense_buff'),
                        ('bond_inspiration', 'bond_inspiration')):
        fraction, until = getattr(unit, prefix + '_fraction'), getattr(unit, prefix + '_until')
        if not fraction or t + EPS < until:
            continue
        source = battle.units[getattr(unit, prefix + '_source_idx')]
        with _effect(battle, source, unit, key, 'expire', t,
                     amount=0, fraction=fraction, duration=0., expires_at=until,
                     source_idx=source.idx, recipient_idx=unit.idx,
                     source_cast_index=getattr(unit, prefix + '_cast_index'),
                     reason='duration'):
            setattr(unit, prefix + '_fraction', 0.)
            setattr(unit, prefix + '_until', 0.)
            setattr(unit, prefix + '_source_idx', None)
            setattr(unit, prefix + '_cast_index', None)
            battle._emit_state(unit, t)


def before_basic(battle, unit, target, t):
    """An attempted basic against a different enemy loses the shared lock buff."""
    if not battle._arena_on or _tempo_spec(unit)[0] is None:
        return
    expire(battle, unit, t)
    if unit.tempo_stacks and unit.tempo_target_idx != target.idx:
        _reset_tempo(battle, unit, t, 'retarget')


def after_basic(battle, unit, target, t, action_index, actual_hp):
    key, tier, base, item = _tempo_spec(unit)
    if (not battle._arena_on or key is None or not unit.alive
            or unit.team == target.team or actual_hp <= 0):
        return False
    before_basic(battle, unit, target, t)
    previous = unit.tempo_stacks
    stacks = min(3, previous + 1)
    with _effect(battle, unit, unit, key, 'tempo', t,
                 amount=0, stacks=stacks, previous_stacks=previous,
                 gained=stacks - previous, fraction=(base + item) * stacks,
                 base_fraction=base * stacks, item_fraction=item * stacks, bond_tier=tier,
                 duration=4., expires_at=t + 4., action_index=action_index,
                 origin_idx=target.idx, origin_pos=target.pos,
                 reason='same_target_actual_basic_hp'):
        unit.tempo_stacks, unit.tempo_target_idx = stacks, target.idx
        unit.tempo_until = t + 4.
        battle._emit_state(unit, t)
    return True


def tempo_multiplier(battle, unit, t):
    if not battle._arena_on or not unit.tempo_stacks or t + EPS >= unit.tempo_until:
        return 1.
    _, _, base, item = _tempo_spec(unit)
    return 1. + (base + item) * unit.tempo_stacks


def damage_multiplier(battle, unit, t):
    """Direct hits only; independently timed bond and augment take the stronger."""
    if not battle._arena_on:
        return 1.
    active = [getattr(unit, prefix + '_fraction')
              for prefix in ('offense_buff', 'bond_inspiration')
              if t + EPS < getattr(unit, prefix + '_until')]
    return 1. + max(active, default=0.)


def after_native_energy(battle, source, patient, actual, t, cast_index):
    key = 'native_inspiration'
    spec = AUGMENTS[key]
    native = (isinstance(cast_index, int) and 0 <= cast_index < len(battle.events)
              and battle.events[cast_index][1:3] == ('cast', source.idx)
              and battle.events[cast_index][4] == 'arena_' + source.ult_arch
              and source.piece.species_id in (121, 171, 164))
    if (not battle._arena_on or not native or not source.alive or not patient.alive
            or source is patient or source.team != patient.team or actual <= 0
            or key not in battle.arena_teams[patient.team]
            or not _ready(patient, key, t, spec['cooldown'], spec['limit'])):
        return False
    # Native-only entry: the caller is arena_skills._energy after its own
    # skill_effect closes. Combo, passive, basic, drain and TM energy do not call it.
    with _effect(battle, source, patient, key, 'offense_buff', t, cast_index,
                 amount=0, fraction=spec['damage_bonus'], duration=spec['duration'],
                 expires_at=t + spec['duration'], source_idx=source.idx,
                 recipient_idx=patient.idx, native_energy_amount=actual,
                 reason='other_native_effective_energy'):
        patient.offense_buff_fraction = spec['damage_bonus']
        patient.offense_buff_until = t + spec['duration']
        patient.offense_buff_source_idx, patient.offense_buff_cast_index = source.idx, cast_index
        _used(patient, key, t, spec['cooldown'])
        battle._emit_state(patient, t)
    return True


def after_dot(battle, source, patient, kind, t, actual_hp, action_index):
    key = 'contagion_orb'
    if (not battle._arena_on or not status.STATUS_ON
            or source is None or not source.alive or not patient.alive
            or source.team == patient.team or getattr(source, 'item_key', None) != key
            or kind not in ('burn', 'poison') or actual_hp <= 0):
        return False
    st = getattr(patient, '_st', None)
    if (st is None or st.debuff != kind or st.debuff_source_idx != source.idx
            or not st.debuff_spreadable):
        return False
    spec = FINISHED[key]
    ledger_key = (patient.idx, kind)
    ledger = source.contagion_counts.get(ledger_key)
    if ledger is None or ledger['epoch'] != st.debuff_source_epoch:
        ledger = {'epoch': st.debuff_source_epoch, 'ticks': 0}
        source.contagion_counts[ledger_key] = ledger
    ledger['ticks'] = min(spec['dot_ticks'], ledger['ticks'] + 1)
    if (ledger['ticks'] < spec['dot_ticks'] or patient.idx in source.contagion_used_targets
            or not _ready(source, key, t, spec['cooldown'], spec['limit'])):
        return False
    # Snapshot one eligible enemy. An occupied status slot is never refreshed,
    # so spreading cannot steal another caster's existing DOT attribution.
    candidates = [enemy for enemy in battle.units
                  if enemy is not patient and enemy.alive and enemy.team == patient.team
                  and abs(enemy.pos[0] - patient.pos[0]) + abs(enemy.pos[1] - patient.pos[1]) <= 1
                  and enemy._st.debuff is None
                  and not set(enemy.piece.types).intersection(status.IMMUNE_TYPES[kind])]
    recipient = min(candidates, key=lambda enemy: (
        abs(enemy.pos[0] - patient.pos[0]) + abs(enemy.pos[1] - patient.pos[1]),
        battle._target_key(source, enemy)), default=None)
    if recipient is None:
        return False
    with _effect(battle, source, recipient, key, 'spread', t,
                 amount=0, status_kind=kind, origin_idx=patient.idx,
                 origin_pos=patient.pos, source_idx=source.idx, recipient_idx=recipient.idx,
                 action_index=action_index, dot_ticks=spec['dot_ticks'], applied=True,
                 non_spreading=True, duration=status.DEBUFFS[kind]['dur'],
                 expires_at=t + status.DEBUFFS[kind]['dur'],
                 reason='owned_actual_dot_three_ticks'):
        status.apply_debuff(battle, recipient, kind, t, source=source, non_spreading=True)
        source.contagion_used_targets.add(patient.idx)
        _used(source, key, t, spec['cooldown'])
    return True
