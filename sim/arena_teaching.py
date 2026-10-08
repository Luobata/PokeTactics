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


def _active_fields(battle, team, t):
    return [field for field in getattr(battle, 'rock_fields', ())
            if field['team'] == team and field['expires_at'] > t + arena_fields.EPS
            and field['cells']]


def _has_layer(battle, team):
    return any(friend.alive and friend.team == team
               and arena_skills.skill_of(friend.piece.species_id)['category'] == 'terrain'
               for friend in battle.units)


def _tactical_ready(battle, unit, target, t):
    """Wait for useful terrain once; never spend roar into a blocked landing.

    This uses current combat facts, not an extra saved policy or a new action.
    Six seconds bounds setup waiting even if the expected layer never casts.
    """
    if unit.technique == 'thunder':
        from arena_weather import active, has_rain_setter
        return (active(battle, t) == 'rain' or t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
                or not has_rain_setter(battle, unit.team))
    if unit.technique == 'roar':
        destination = battle._knock_cell(target, unit.pos)
        if destination is None:
            return False
        fields = _active_fields(battle, unit.team, t)
        if any(destination in field['cells'] for field in fields):
            return True
        return (t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
                or not (fields or _has_layer(battle, unit.team)))
    if unit.technique == 'rapid_spin':
        enemy_team = 1 - unit.team
        fields = _active_fields(battle, enemy_team, t)
        if any(abs(cell[0] - unit.pos[0]) + abs(cell[1] - unit.pos[1]) <= 1
               for field in fields for cell in field['cells']):
            return True
        return (t + arena_fields.EPS >= TACTICAL_WAIT_SECONDS
                or not (fields or _has_layer(battle, enemy_team)))
    return True


def after_basic(battle, unit, target, t, actual_hp=None):
    from arena_actions import action
    with action(battle, unit, t, MOVES.get(unit.technique)):
        return _after_basic(battle, unit, target, t, actual_hp)


def _after_basic(battle, unit, target, t, actual_hp=None):
    if not battle._arena_on:
        return
    key = unit.technique
    if key not in (*MOVES, 'roar') or unit.technique_used or not unit.alive:
        return
    # A lethal basic attack has already resolved. Preserve the machine until
    # another basic attack can follow up against a live target.
    if (not target.alive or not _tactical_ready(battle, unit, target, t)
            or key == 'thunder' and actual_hp is not None and actual_hp <= 0):
        return
    unit.technique_used = True
    if key == 'roar':
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
        return
    move = MOVES[key]
    if key == 'thunder':
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
        return
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
