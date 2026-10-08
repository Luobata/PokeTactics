"""Round loot is deterministic, consumable inventory, independent of playback."""
import items
import techniques


COMPONENT_CHOICE_ROUNDS = (3, 6)


def component_choice(run_id, round_no, seat):
    """A milestone supply is separate from ordinary, result-dependent loot."""
    if round_no not in COMPONENT_CHOICE_ROUNDS or type(seat) is not int or not 0 <= seat < 8:
        raise ValueError('组件补给轮次或席位无效')
    return {'id': f'{run_id}:r{round_no}:s{seat}:component',
            'round': round_no, 'seat': seat, 'options': list(items.COMPONENT_ORDER),
            'status': 'pending', 'choice': None, 'closed_reason': None}


def claim_component(seat, reward, choice):
    """Validate before granting; a repeated identical claim is idempotent."""
    if (not isinstance(choice, str) or choice not in items.COMPONENT_ORDER
            or choice not in reward['options'] or reward['seat'] != seat.seat):
        raise ValueError('请选择本次补给中的有效组件')
    if reward['status'] != 'pending':
        if reward['status'] == 'claimed' and reward['choice'] == choice:
            return False
        raise ValueError('这份组件补给已处理，不能更换领取结果')
    grant_rewards(seat, [{'kind': 'component', 'key': choice}])
    reward.update(status='claimed', choice=choice)
    return True


def bot_component_choice(seat, options, rng):
    """Prefer a component that unlocks a recipe; break equal scores by seed."""
    from collections import Counter
    counts = seat.inventory.components

    def craftable(pair, extra=None):
        return all(counts[key] + (key == extra) >= amount
                   for key, amount in Counter(pair).items())

    def score(component):
        return sum(any(craftable(pair, component) for pair in spec['pairs'] or ())
                   and not any(craftable(pair) for pair in spec['pairs'] or ())
                   for key, spec in items.catalog('arena_v1').items()
                   if key not in ('lucky_egg', 'evo_stone'))

    scores = {key: score(key) for key in options}
    best = max(scores.values())
    return rng.choice([key for key in options if scores[key] == best])


def component_choice_view(reward):
    """Attach recipe information without changing the persisted choice ledger."""
    options = []
    for component in reward['options']:
        recipes = [{'id': key, 'name': spec['name'],
                    'recipes': [list(pair) for pair in spec['pairs']]}
                   for key, spec in items.catalog('arena_v1').items()
                   if any(component in pair for pair in spec['pairs'] or ())]
        options.append({'id': component, 'name': items.COMPONENT_NAMES[component],
                        'recipes': [row['id'] for row in recipes],
                        'recipe_details': recipes})
    return {**reward, 'options': options}


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
        spec = techniques.view(key, 'arena_v1')
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
