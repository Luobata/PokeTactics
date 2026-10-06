"""Finite arena TM follow-ups use the same typed hit and state pipeline."""

MOVES = {
    'thunderbolt': {'name': 'thunderbolt', 'type': 'ELECTRIC', 'power': 35},
    'ice_beam': {'name': 'ice_beam', 'type': 'ICE', 'power': 35},
    'toxic': {'name': 'sludge_bomb', 'type': 'POISON', 'power': 25},
    'earthquake': {'name': 'earthquake', 'type': 'GROUND', 'power': 30},
}


def after_basic(battle, unit, target, t):
    key = unit.technique
    if key not in MOVES or unit.technique_used or not unit.alive:
        return
    # A lethal basic attack has already resolved. Preserve the machine until
    # another basic attack can follow up against a live target.
    if not target.alive:
        return
    unit.technique_used = True
    move = MOVES[key]
    victims = [target]
    if key == 'earthquake':
        victims += sorted((enemy for enemy in battle.units if enemy.alive
                           and enemy.team != unit.team and enemy is not target
                           and abs(target.pos[0] - enemy.pos[0]) + abs(target.pos[1] - enemy.pos[1]) <= 1),
                          key=lambda enemy: battle._target_key(unit, enemy))[:2]
    for victim in victims:
        if not victim.alive:
            continue
        damage = battle._move_damage(unit, victim, move)
        # Cast events carry actual move type/name; damage, death, status and
        # energy are emitted by the authoritative engine and replayed together.
        battle._land_hit(unit, victim, damage, t, move=move, primary=True, cast=True)
