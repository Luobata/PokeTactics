"""Round loot is deterministic, consumable inventory, independent of playback."""
import items
import techniques


def reward_view(grant):
    if not isinstance(grant, dict) or set(grant) != {'kind', 'key'}:
        raise ValueError('奖励物品字段无效')
    kind, key = grant['kind'], grant['key']
    if not isinstance(key, str):
        raise ValueError('奖励物品编号无效')
    if kind == 'component' and key in items.COMPONENT_NAMES:
        name, description = items.COMPONENT_NAMES[key], '装备组件，可与另一组件合成。'
    elif kind == 'item' and key in items.catalog('arena_v1') and key not in ('lucky_egg', 'evo_stone'):
        name, description = items.FINISHED[key]['name'], '成品装备，可直接装备到精灵。'
    elif kind == 'technique' and key in techniques.ids_for('arena_v1'):
        spec = techniques.view(key)
        name, description = spec['name'], spec['description']
    else:
        raise ValueError('未知回合奖励')
    return {**grant, 'name': name, 'description': description}


def roll_rewards(rng, result, ruleset='arena_v1'):
    if ruleset != 'arena_v1' or result not in ('win', 'loss', 'draw'):
        raise ValueError('回合奖励规则或胜负无效')
    pools = {
        'component': list(items.COMPONENT_ORDER),
        'item': sorted(set(items.catalog(ruleset)) - {'lucky_egg', 'evo_stone'}),
        'technique': list(techniques.ids_for(ruleset)),
    }
    grants = []
    for _ in range(2 if result == 'win' else 1):
        kind = rng.choice(list(pools))
        grants.append({'kind': kind, 'key': rng.choice(pools[kind])})
    return grants


def grant_rewards(seat, grants):
    # Validate the entire packet before altering any resource.
    for grant in grants:
        reward_view(grant)
    for grant in grants:
        kind, key = grant['kind'], grant['key']
        if kind == 'component':
            seat.inventory.add_component(key)
            seat.item_drops += 1
        elif kind == 'item':
            seat.inventory.finished.append(key)
            seat.item_drops += 1
        else:
            seat.inventory.techniques[key] += 1
