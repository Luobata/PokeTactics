"""Finite arena TM follow-ups use the same typed hit and state pipeline."""
import arena_fields
import arena_skills

MOVES = {
    'surf': {'name': 'surf', 'type': 'WATER', 'power': 35},
    'thunderbolt': {'name': 'thunderbolt', 'type': 'ELECTRIC', 'power': 35},
    'thunder': {'name': 'thunder', 'type': 'ELECTRIC', 'power': 65},
    'ice_beam': {'name': 'ice_beam', 'type': 'ICE', 'power': 35},
    'toxic': {'name': 'sludge_bomb', 'type': 'POISON', 'power': 25},
    'earthquake': {'name': 'earthquake', 'type': 'GROUND', 'power': 30},
    'rapid_spin': {'name': 'rapid_spin', 'type': 'NORMAL', 'power': 20},
}


TACTICAL_WAIT_SECONDS = 6.

# 技能机成长：可用次数 = 携带者星级；每次触发后需 3 次有效普攻再装填。
TECHNIQUE_REARM_HITS = 3

# 守住：2 秒 20% 减伤窗口；窗口内实际承伤达到最大生命 15% 蓄势 +12%。
PROTECT_REDUCTION = .20
PROTECT_WINDOW_SECONDS = 2.
PROTECT_CHARGE_FRACTION = .15
PROTECT_EMPOWER = .12
# 帮助：被标记友军的下一次原生主命中 +15%。
HELPING_HAND_EMPOWER = .15


def technique_limit(unit):
    return max(1, int(getattr(unit.piece, 'star', 1)))


def technique_available(unit):
    return unit.technique_used < technique_limit(unit) and unit.technique_rearm <= 0


def technique_spend(unit):
    unit.technique_used += 1
    unit.technique_rearm = TECHNIQUE_REARM_HITS


def _active_fields(battle, team, t):
    return [field for field in getattr(battle, 'rock_fields', ())
            if field['team'] == team and field['expires_at'] > t + arena_fields.EPS
            and field['cells']]


def _has_layer(battle, team):
    return any(friend.alive and friend.team == team
               and arena_skills.skill_of(friend.piece.species_id)['category'] == 'terrain'
               for friend in battle.units)


def _thunder_ready(battle, unit, target, t):
    from arena_weather import active, has_rain_setter
    return (active(battle, t) == 'rain' or t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
            or not has_rain_setter(battle, unit.team))


def _roar_ready(battle, unit, target, t):
    destination = battle._knock_cell(target, unit.pos)
    if destination is None:
        return False
    fields = _active_fields(battle, unit.team, t)
    if any(destination in field['cells'] for field in fields):
        return True
    return (t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
            or not (fields or _has_layer(battle, unit.team)))


def _rapid_spin_ready(battle, unit, target, t):
    enemy_team = 1 - unit.team
    fields = _active_fields(battle, enemy_team, t)
    if any(abs(cell[0] - unit.pos[0]) + abs(cell[1] - unit.pos[1]) <= 1
           for field in fields for cell in field['cells']):
        return True
    return (t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
            or not (fields or _has_layer(battle, enemy_team)))


# key -> tactical wait predicate; keys without an entry are always ready.
_TACTICAL_CONDITIONS = {'thunder': _thunder_ready, 'roar': _roar_ready,
                        'rapid_spin': _rapid_spin_ready}


def _tactical_ready(battle, unit, target, t):
    """Wait for useful terrain once; never spend roar into a blocked landing.

    This uses current combat facts, not an extra saved policy or a new action.
    Six seconds bounds setup waiting even if the expected layer never casts.
    """
    condition = _TACTICAL_CONDITIONS.get(unit.technique)
    return True if condition is None else condition(battle, unit, target, t)


def _taunt_after_basic(battle, unit, target, t, key):
    cast_index = len(battle.events)
    battle._land_hit(unit, target, 0, t,
                     move={'name': 'taunt', 'type': 'NORMAL', 'power': 0}, cast=True)
    with battle._skill_effect(unit, target, 'taunt', t, cast_index,
                              duration=2., expires_at=t + 2., technique=key):
        target.taunt_source_idx = unit.idx
        target.taunt_cast_index = cast_index
        target.taunt_until = t + 2.
        target.taunt_ready_at = t + 4.
        target.target_idx = unit.idx
        battle._emit_state(target, t)


def _sleep_powder_after_basic(battle, unit, target, t, key):
    battle._land_hit(unit, target, 0, t,
                     move={'name': 'sleep_powder', 'type': 'GRASS', 'power': 0}, cast=True)
    import status as status_mod
    status_mod.apply_debuff(battle, target, 'sleep', t, source=unit)


def _stealth_rock_after_basic(battle, unit, target, t, key):
    cast_index = len(battle.events)
    battle._land_hit(unit, target, 0, t,
                     move={'name': 'stealth_rock', 'type': 'ROCK', 'power': 0}, cast=True)
    arena_fields.place_rocks(battle, unit, target, t, cast_index)


def _roar_after_basic(battle, unit, target, t, key):
    cast_index = len(battle.events)
    # A finite teaching action owns its own packet, separate from native casts.
    battle._land_hit(unit, target, 0, t,
                     move={'name': 'roar', 'type': 'NORMAL', 'power': 0}, cast=True)
    effect_index = len(battle.events)
    arena_skills._knockback(battle, unit, target, t, cast_index)
    if len(battle.events) > effect_index:
        effect = battle.events[effect_index]
        if effect[1] == 'skill_effect' and effect[5] == 'knockback':
            # Keep the movement packet and cast ownership intact while
            # attributing this teaching effect to its actual move.
            effect[6]['move_name'] = 'roar'
            battle.events[effect_index] = (*effect[:4], 'roar', *effect[5:])


def _thunder_after_basic(battle, unit, target, t, key):
    move = MOVES[key]
    from arena_weather import active
    from arena_combinations import _effect
    guaranteed = active(battle, t) == 'rain'
    accuracy_roll = None if guaranteed else battle.rng.random()
    hit = guaranteed or accuracy_roll < .70
    dodge_roll = None
    if hit and not guaranteed and target.item_dodge > 0:
        dodge_roll = battle.rng.random()
        if dodge_roll < target.item_dodge:
            from arena_traits import prevent_dodge
            hit = prevent_dodge(battle, unit, target, dodge_roll, t)
    cast_index = len(battle.events)
    if not hit:
        battle._land_hit(unit, target, 0, t, move=move, cast=True)
        battle.events.append((t, 'miss', unit.idx, target.idx))
        with _effect(battle, unit, target, 'arena_weather', 'accuracy', t, cast_index,
                     amount=0, technique=key, hit=False, guaranteed=False,
                     accuracy=.70, accuracy_roll=accuracy_roll, dodge_roll=dodge_roll,
                     reason='thunder_missed'):
            battle._emit_state(unit, t)
        return
    damage = battle._move_damage(unit, target, move)
    actual = battle._land_hit(unit, target, damage, t, move=move, primary=True, cast=True)
    from arena_interactions import after_primary
    after_primary(battle, unit, target, move, actual, t, cast_index)
    with _effect(battle, unit, target, 'arena_weather', 'accuracy', t, cast_index,
                 amount=0, technique=key, hit=True, guaranteed=guaranteed,
                 accuracy=1. if guaranteed else .70,
                 accuracy_roll=accuracy_roll, dodge_roll=dodge_roll,
                 immune=damage <= 0, reason='rain_thunder_guaranteed' if guaranteed
                        else 'thunder_accuracy_passed'):
        battle._emit_state(unit, t)


def _damage_after_basic(battle, unit, target, t, key):
    """Default handler for MOVES members without a registered mechanic."""
    move = MOVES[key]
    victims = [target]
    if key in ('surf', 'earthquake'):
        victims += sorted((enemy for enemy in battle.units if enemy.alive
                           and enemy.team != unit.team and enemy is not target
                           and abs(target.pos[0] - enemy.pos[0]) + abs(target.pos[1] - enemy.pos[1]) <= 1),
                          key=lambda enemy: battle._target_key(unit, enemy))[:2]
    cast_index = len(battle.events)
    for victim in victims:
        if not unit.alive:
            break
        if not victim.alive:
            continue
        damage = battle._move_damage(unit, victim, move)
        # Cast events carry actual move type/name; damage, death, status and
        # energy are emitted by the authoritative engine and replayed together.
        action_index = len(battle.events)
        actual = battle._land_hit(unit, victim, damage, t, move=move, primary=True, cast=True)
        if victim is target:
            from arena_interactions import after_primary
            after_primary(battle, unit, victim, move, actual, t, action_index)
    if key == 'rapid_spin' and unit.alive:
        arena_fields.clear_near(battle, unit, t, cast_index, limit=3)


def _helping_hand_after_basic(battle, unit, target, t, key):
    """标记两格内攻击最高的其他存活友军；没有合法友军时不消耗次数。"""
    candidates = [friend for friend in battle.units
                  if friend.alive and friend.team == unit.team and friend is not unit
                  and not friend.helping_hand_mark
                  and abs(friend.pos[0] - unit.pos[0]) + abs(friend.pos[1] - unit.pos[1]) <= 2]
    recipient = min(candidates,
                    key=lambda friend: (-friend.attack, battle._target_key(unit, friend)),
                    default=None)
    if recipient is None:
        return False
    cast_index = len(battle.events)
    battle._land_hit(unit, recipient, 0, t,
                     move={'name': 'helping_hand', 'type': 'NORMAL', 'power': 0}, cast=True)
    with battle._skill_effect(unit, recipient, 'helping_hand', t, cast_index,
                              fraction=HELPING_HAND_EMPOWER, technique=key):
        recipient.helping_hand_mark = True
        battle._emit_state(recipient, t)
    return True


# Dispatch table for mechanic techniques; MOVES members without an entry fall
# through to the shared damage handler above. Triggerable keys are exactly
# _HANDLERS keys plus MOVES. A handler returning False keeps the charge.
_HANDLERS = {'taunt': _taunt_after_basic,
             'sleep_powder': _sleep_powder_after_basic,
             'stealth_rock': _stealth_rock_after_basic,
             'roar': _roar_after_basic,
             'thunder': _thunder_after_basic,
             'helping_hand': _helping_hand_after_basic}


def after_basic(battle, unit, target, t, actual_hp=None):
    from arena_actions import action
    with action(battle, unit, t, MOVES.get(unit.technique)):
        return _after_basic(battle, unit, target, t, actual_hp)


def _after_basic(battle, unit, target, t, actual_hp=None):
    if not battle._arena_on:
        return
    key = unit.technique
    if (key not in MOVES and key not in _HANDLERS) \
            or not technique_available(unit) or not unit.alive:
        return
    # A lethal basic attack has already resolved. Preserve the machine until
    # another basic attack can follow up against a live target.
    if (not target.alive or not _tactical_ready(battle, unit, target, t)
            or key == 'thunder' and actual_hp is not None and actual_hp <= 0):
        return
    technique_fired = _HANDLERS.get(key, _damage_after_basic)(battle, unit, target, t, key)
    if technique_fired is not False:
        technique_spend(unit)


def after_hit_taken(battle, unit, source, actual_hp, t, action_index):
    """守住：首次实际受击开启减伤窗口，窗口内承伤累计达标后蓄势。"""
    if (not battle._arena_on or getattr(unit, 'technique', None) != 'protect'
            or not unit.alive or actual_hp <= 0):
        return
    if unit.protect_window_until > t + arena_fields.EPS:
        if not unit.protect_charged:
            unit.protect_accum += actual_hp
            threshold = unit.max_hp * PROTECT_CHARGE_FRACTION
            if unit.protect_accum >= threshold > 0:
                with battle._skill_effect(unit, unit, 'protect_charge', t, action_index,
                                          fraction=PROTECT_EMPOWER,
                                          accumulated=unit.protect_accum,
                                          threshold=int(threshold), technique='protect',
                                          reason='window_damage_threshold'):
                    unit.protect_charged = True
                    unit.protect_empower = True
                    battle._emit_state(unit, t)
        return
    if not technique_available(unit):
        return
    technique_spend(unit)
    unit.protect_window_until = t + PROTECT_WINDOW_SECONDS
    unit.protect_accum = 0
    unit.protect_charged = False
    with battle._skill_effect(unit, unit, 'protect', t, action_index,
                              reduction=PROTECT_REDUCTION,
                              duration=PROTECT_WINDOW_SECONDS,
                              expires_at=t + PROTECT_WINDOW_SECONDS, technique='protect',
                              origin_idx=source.idx if source is not None else None,
                              reason='first_actual_direct_hit_taken'):
        # 不覆盖既有的更强减伤窗口（与原生减伤同一槽位语义）。
        if not (unit.temp_dr_until > t and unit.temp_dr > PROTECT_REDUCTION):
            unit.temp_dr, unit.temp_dr_until = PROTECT_REDUCTION, t + PROTECT_WINDOW_SECONDS
        battle._emit_state(unit, t)


def after_ally_debuff(battle, source, patient, kind, t):
    """治愈铃声：友军被新施加主要异常后，净化两格内一名其他队友的该异常。"""
    if not battle._arena_on:
        return
    for carrier in battle.units:
        if (carrier is patient or not carrier.alive or carrier.team != patient.team
                or getattr(carrier, 'technique', None) != 'heal_bell'
                or not technique_available(carrier)):
            continue
        candidates = [friend for friend in battle.units
                      if friend.alive and friend.team == carrier.team and friend is not carrier
                      and getattr(getattr(friend, '_st', None), 'debuff', None) == kind
                      and abs(friend.pos[0] - carrier.pos[0])
                      + abs(friend.pos[1] - carrier.pos[1]) <= 2]
        recipient = (patient if patient in candidates else
                     min(candidates, key=lambda friend: battle._target_key(carrier, friend),
                         default=None))
        if recipient is None:
            continue
        import status as status_mod
        with battle._skill_effect(carrier, recipient, 'heal_bell', t, None,
                                  status_kind=kind, technique='heal_bell',
                                  origin_idx=source.idx if source is not None else None,
                                  reason='ally_major_status_applied'):
            if status_mod.cleanse(battle, recipient, t, kinds={kind}):
                technique_spend(carrier)
                battle._emit_state(recipient, t)


def prepare_native_primary(battle, unit, damage, t):
    """Consume one-shot teaching marks before a native primary hit lands."""
    if not battle._arena_on or not unit.alive or damage <= 0:
        return damage, None
    marks = [(key, fraction) for key, fraction, held in (
        ('protect', PROTECT_EMPOWER, unit.protect_empower),
        ('helping_hand', HELPING_HAND_EMPOWER, unit.helping_hand_mark)) if held]
    if not marks:
        return damage, None
    extra = sum(int(damage * fraction) for _, fraction in marks)
    if not extra:
        return damage, None
    unit.protect_empower = False
    unit.helping_hand_mark = False
    return damage + extra, {'marks': [(key, fraction, int(damage * fraction))
                                      for key, fraction in marks],
                            'baseline_damage': damage}


def settle_native_primary(battle, unit, target, context, t, cast_index):
    """Annotate consumed teaching marks on the settled native primary hit."""
    if context is None:
        return
    for key, fraction, extra in context['marks']:
        with battle._skill_effect(unit, target, 'native_empower', t, cast_index,
                                  amount=extra, extra_damage=extra, fraction=fraction,
                                  baseline_damage=context['baseline_damage'],
                                  technique=key, reason='empowered_native_primary'):
            battle._emit_state(unit, t)
