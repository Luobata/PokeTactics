"""Expected additive v5 arena migration; no production codec helpers are used."""
import copy
from collections import Counter

NEW_SYNERGY_MACHINES = ('sunny_day', 'rain_dance', 'thunder')
NEW_TECHNIQUE_GROWTH_MACHINES = ('stealth_rock', 'taunt', 'sleep_powder')
NEW_SUPPORT_MACHINES = ('protect', 'helping_hand', 'heal_bell')


def _held_counts(payload):
    """Per-species pool occupation exactly as the codec counts it.

    The player seat's board records mirror its grid cells (the codec only
    instantiates the grid), so count grid for seat 0 and board for bots.
    """
    held = Counter()
    for seat in payload['seats']:
        for owned in seat['bench']:
            held.update(owned['sources'])
        if seat.get('grid') is not None:
            for _, _, owned in seat['grid']:
                held.update(owned['sources'])
        else:
            for owned in seat['board']:
                held.update(owned['sources'])
        for sid in seat['shop']:
            if sid is not None:
                held[sid] += 1
    return held


def downgrade_to_pre_legendary_pool(payload):
    """Rewrite a current-rules payload's pool to the 48-species 22/18/12 era.

    Fabricated predecessor saves (current session + swapped fingerprint) must
    keep the accounting their fingerprint era could actually produce.
    """
    import arena
    from session_save import PRE_LEGENDARY_POOL_BY_COST
    held = _held_counts(payload)
    later = set(arena.LEGENDARY_ROSTER) | set(arena.REBALANCE_ROSTER)
    payload['pool'] = {str(sid): PRE_LEGENDARY_POOL_BY_COST[arena.ROSTER[sid][0]] - held[sid]
                       for sid in arena.ROSTER if sid not in later}
    return payload


def migrate_legendary_pool(pool, held):
    """Later-species refill + tightened caps (20/16/10/10/8) for old saves.

    Species absent from the old payload refill at the new cap; committed species
    keep their old-cap conservation proof in the codec and their remaining stock
    is clamped to the new cap here, mirroring session_save's migration.
    """
    import arena
    migrated = dict(pool)
    for sid in set(arena.LEGENDARY_ROSTER) | set(arena.REBALANCE_ROSTER):
        migrated.setdefault(str(sid), arena.pool_cap(sid))
    for key, count in pool.items():
        cap = arena.pool_cap(int(key))
        migrated[key] = max(0, min(cap, cap - held[int(key)]))
    return migrated


def with_synergy_defaults(payload):
    """Keep every old field, adding only implicit live choices and zero new TMs."""
    expected = copy.deepcopy(payload)
    if expected.get('ruleset') != 'arena_v1':
        return expected
    for seat in expected['seats']:
        for owned in seat['board'] + seat['bench']:
            owned.setdefault('arena_trait', None)
        for _, _, owned in seat.get('grid', []):
            owned.setdefault('arena_trait', None)
        for key in NEW_SYNERGY_MACHINES + NEW_TECHNIQUE_GROWTH_MACHINES + NEW_SUPPORT_MACHINES:
            seat['techniques'].setdefault(key, 0)
    for member in expected.get('opponent_comp') or []:
        member.setdefault('arena_trait', None)
    # Post-battle attribution ledgers: old builds never wrote them; decoding
    # defaults them to empty and re-encoding persists that.
    expected.setdefault('damage_taken_by', {})
    expected.setdefault('last_defeat', {})
    # Pending augment rows predate the free reroll: decoding treats them as
    # still refreshable and re-encoding persists the flag.
    for row in expected.get('arena', {}).get('pending', []):
        row.setdefault('rerolled', False)
    # Arena growth meta is additive: old builds never wrote the unlock
    # snapshot, per-run challenge counters or new-challenge announcements.
    if 'arena' in expected:
        expected['arena'].setdefault('meta', {
            'unlocks': {'augments': [], 'traits': []},
            'run': {'kills': 0, 'bonds': [], 'combos': 0, 'streak': 0},
            'new_challenges': []})
    # 4/5 费传说档与上限收紧（2026-10-11）：全部已验证竞技前任都早于它。
    expected['pool'] = migrate_legendary_pool(expected['pool'], _held_counts(expected))
    return expected
