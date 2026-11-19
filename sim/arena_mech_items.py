"""arena_v2 mechanic items: equipment that changes how a unit fights.

The eight numeric v1 items (专爱头巾, 疾风羽, 聚光镜, three scarves, 天气石, 亮粉)
retire from arena_v2 crafting and loot; their component pairs now craft the
items below. Four treasures have no recipe and come from draft rounds and wild
wins. Retired items stay in the catalog so existing saves keep loading.

Every item is designed to plug into another system (bond breakpoints, terrain,
skill categories, augments, orders) so that combinations, not raw numbers,
decide its value. ``GUIDE`` documents those links for the in-game advisor.
"""
from arena_effects import EffectSpec, fire

RETIRED_IN_V2 = frozenset({'choice_band', 'swift_feather', 'focus_lens', 'scarf_fire', 'scarf_water',
                           'scarf_electric', 'weather_stone', 'bright_powder'})

MECH_ITEMS = {
    'boomerang': {'name': '回旋镖', 'pairs': (('band', 'magnet'),),
                  'description': '有效普攻后弹射到目标 2 格内最近的另一名敌人，造成本次实际伤害的 50%。'},
    'impact_gauntlet': {'name': '冲击护手', 'pairs': (('shoes', 'shoes'),),
                        'description': '每第 3 次有效普攻把目标击退 1 格；击退会触发岩钉入格、乘隙追击、逐风鸣铃、潮汐甲壳等联动。'},
    'echo_bell': {'name': '回响铃', 'pairs': (('magnet', 'bell'),),
                  'description': '本命技能主命中造成实际伤害后，对同一目标追加一次 45% 的回响伤害。'},
    'flame_orb': {'name': '火焰宝珠', 'pairs': (('charcoal', 'magnet'),),
                  'description': '有效普攻使没有异常的目标灼伤（同一目标 4 秒一次）。为侵蚀、扩散宝珠、燎原等提供灼伤来源。'},
    'toxic_orb': {'name': '剧毒宝珠', 'pairs': (('mysticwater', 'magnet'),),
                  'description': '有效普攻使没有异常的目标中毒（同一目标 4 秒一次）。为毒蚀、毒性催化、侵蚀等提供中毒来源。'},
    'static_glove': {'name': '静电手套', 'pairs': (('spark', 'magnet'), ('spark', 'spark')),
                     'description': '每第 4 次有效普攻使目标麻痹；携带者对麻痹目标伤害 +15%。为“对已控制目标追击”类本命提供条件。'},
    'taunt_bell': {'name': '挑衅铃', 'pairs': (('hardstone', 'hardstone'), ('magnet', 'hardstone')),
                   'description': '开战时嘲讽 2 格内所有敌人 2.5 秒，期间携带者受到伤害 -25%。把火力拉到带反伤、护盾的前排。'},
    'red_card': {'name': '红牌', 'pairs': (('hardstone', 'shoes'),),
                 'description': '每场前 2 次被近战直接命中时，把攻击者推开最多 2 格（会触发岩钉与击退联动）。'},
    'weakness_policy': {'name': '弱点保险', 'pairs': (), 'treasure': True,
                        'description': '宝物（选秀 / 野怪掉落）。第一次被效果拔群的攻击命中后，本场攻击与特攻 +30%、5 秒攻速 +25%。'},
    'reaper_scale': {'name': '逆鳞', 'pairs': (), 'treasure': True,
                     'description': '宝物。每击倒一名敌人：获得 30 能量，3 秒攻速 +25%。连杀滚雪球。'},
    'revival_seed': {'name': '复活种子', 'pairs': (), 'treasure': True,
                     'description': '宝物。每场一次：相邻队友受到致命伤时改为保留 25% 生命，携带者失去 15% 最大生命。'},
    'rally_whistle': {'name': '号令哨', 'pairs': (), 'treasure': True,
                      'description': '宝物。携带者施放本命后，2 格内所有队友 3 秒攻速 +20%。'},
}
for _spec in MECH_ITEMS.values():
    _spec.update(arena_only=True, depth_only=True)
TREASURES = tuple(key for key, spec in MECH_ITEMS.items() if spec.get('treasure'))

# Visible carrier policy (owned piece → score or None) shared by bots and the advisor.
DEPTH_CRAFT_ORDER = ('boomerang', 'impact_gauntlet', 'echo_bell', 'flame_orb', 'toxic_orb',
                     'static_glove', 'taunt_bell', 'red_card', 'weakness_policy', 'reaper_scale',
                     'revival_seed', 'rally_whistle')


def carrier_rank(owned, key):
    if key.endswith('_plus'):
        key = key[:-5]
    from arena_skills import skill_of
    from profiles import effective_range
    piece = owned.piece
    role = getattr(piece, 'role_key', 'attack')
    ranged = effective_range(piece) > 1
    skill = skill_of(piece.species_id)
    if key == 'boomerang':
        return 3 if role == 'attack' and ranged else 2 if role == 'attack' else 1
    if key == 'impact_gauntlet':
        return 3 if role == 'attack' and not ranged else 2 if role == 'defense' else 1
    if key == 'echo_bell':
        if skill.get('targeting') != 'enemy' or not skill.get('power'):
            return None
        return 3 if skill['power'] >= 60 else 2
    if key in ('flame_orb', 'toxic_orb', 'static_glove'):
        return 3 if role == 'attack' else 2 if role == 'defense' else 1
    if key == 'taunt_bell':
        return 3 if role == 'defense' else None
    if key == 'red_card':
        return 3 if role == 'defense' else 1 if not ranged else None
    if key == 'weakness_policy':
        return 3 if role == 'attack' else 2
    if key == 'reaper_scale':
        return 3 if role == 'attack' else 1
    if key == 'revival_seed':
        return 3 if role == 'support' else 2 if role == 'defense' else 1
    if key == 'rally_whistle':
        return 3 if role == 'support' else 2
    return None


# ------------------------------------------------------------------ handlers
def _d():
    import arena_depth
    return arena_depth


def _syn():
    import arena_item_synergy
    return arena_item_synergy


def _owner_basic(inst, unit, target, actual_hp):
    return unit is inst.unit and actual_hp > 0 and target.alive


def _h_boomerang(battle, inst, unit, target, t, actual_hp, **_):
    if not _owner_basic(inst, unit, target, actual_hp):
        return
    d = _d()
    victims = sorted((v for v in battle.units if v.alive and v.team != unit.team and v is not target
                      and d._dist(v, target) <= 2), key=lambda v: (d._dist(v, target), v.local_idx))
    if victims:
        dealt = d._indirect_damage(battle, unit, victims[0], actual_hp * .5, t)
        if dealt:
            fire(battle, inst, victims[0], t, label='回旋镖', kind='damage', value=dealt, spend=False)
        if _syn().is_awakened(unit, 'boomerang'):
            first = victims[0]
            again = sorted((v for v in battle.units if v.alive and v.team != unit.team
                            and v is not target and v is not first and d._dist(v, first) <= 2),
                           key=lambda v: (d._dist(v, first), v.local_idx))
            if again:
                dealt = d._indirect_damage(battle, unit, again[0], actual_hp * .35, t)
                if dealt:
                    fire(battle, inst, again[0], t, label='回旋镖·再弹', kind='damage', value=dealt, spend=False)


def _counter(inst, every):
    inst.state['n'] = inst.state.get('n', 0) + 1
    return inst.state['n'] % every == 0


def _h_impact(battle, inst, unit, target, t, actual_hp, action_index=None, **_):
    awakened = _owner_basic(inst, unit, target, actual_hp) and _syn().is_awakened(unit, 'impact_gauntlet')
    if not _owner_basic(inst, unit, target, actual_hp) or not _counter(inst, 2 if awakened else 3):
        return
    destination = battle._knock_cell(target, unit.pos)
    if destination is None:
        ready = inst.state.setdefault('stun_ready', {})
        if awakened and ready.get(target.idx, 0.) <= t + 1e-9 and _syn().stun(battle, target, t, .8):
            ready[target.idx] = t + 4.
            fire(battle, inst, target, t, label='冲击·眩晕', kind='debuff', spend=False)
        return
    from arena_fields import move_unit
    fire(battle, inst, target, t, label='冲击', kind='move', spend=False)
    move_unit(battle, target, destination, t, action_index, source=unit, reason='knockback')


def _h_echo(battle, inst, unit, target, t, cast_index, lost_hp, **_):
    if unit is not inst.unit or not unit.alive or lost_hp <= 0 or not target.alive:
        return
    dealt = _d()._indirect_damage(battle, unit, target, lost_hp * .45, t)
    if dealt:
        fire(battle, inst, target, t, label='回响', kind='damage', value=dealt, spend=False)
    if _syn().is_awakened(unit, 'echo_bell'):
        d = _d()
        others = sorted((v for v in battle.units if v.alive and v.team != unit.team and v is not target
                         and d._dist(v, target) <= 2), key=lambda v: (d._dist(v, target), v.local_idx))
        if others:
            dealt = d._indirect_damage(battle, unit, others[0], lost_hp * .45, t)
            if dealt:
                fire(battle, inst, others[0], t, label='回响·扩散', kind='damage', value=dealt, spend=False)


def _status_on_basic(kind, label):
    def handler(battle, inst, unit, target, t, actual_hp, **_):
        if not _owner_basic(inst, unit, target, actual_hp):
            return
        ready = inst.state.setdefault('ready', {})
        if ready.get(target.idx, 0.) > t + 1e-9:
            return
        if getattr(getattr(target, '_st', None), 'debuff', None) is not None:
            return
        import status
        if status.apply_debuff(battle, target, kind, t, source=unit):
            ready[target.idx] = t + 4.
            fire(battle, inst, target, t, label=label, kind='debuff', spend=False)
    return handler


def _h_static(battle, inst, unit, target, t, actual_hp, **_):
    awakened = _owner_basic(inst, unit, target, actual_hp) and _syn().is_awakened(unit, 'static_glove')
    if not _owner_basic(inst, unit, target, actual_hp) or not _counter(inst, 3 if awakened else 4):
        return
    import status
    if status.apply_debuff(battle, target, 'para', t, source=unit):
        fire(battle, inst, target, t, label='静电', kind='debuff', spend=False)
        if awakened:
            d = _d()
            others = sorted((v for v in battle.units if v.alive and v.team != unit.team and v is not target
                             and d._dist(v, target) <= 2 and getattr(getattr(v, '_st', None), 'debuff', None) is None),
                            key=lambda v: (d._dist(v, target), v.local_idx))
            if others and status.apply_debuff(battle, others[0], 'para', t, source=unit):
                fire(battle, inst, others[0], t, label='静电·电弧', kind='debuff', spend=False)


def _h_taunt_bell(battle, inst, t, **_):
    unit = inst.unit
    if not unit.alive:
        return
    taunted = 0
    for enemy in battle.units:
        if enemy.alive and enemy.team != unit.team and _d()._dist(enemy, unit) <= 2:
            enemy.taunt_source_idx, enemy.taunt_until = unit.idx, t + 2.5
            enemy.target_idx = unit.idx
            taunted += 1
    if not taunted:
        return
    unit.temp_dr, unit.temp_dr_until = max(unit.temp_dr, .25), t + 2.5
    battle._emit_state(unit, t)
    fire(battle, inst, unit, t, label='挑衅', kind='buff', value=taunted, camera='focus')


def _h_red_card(battle, inst, source, target, actual_hp, t, action_index=None, **_):
    unit = inst.unit
    if (target is not unit or source is None or source.team == unit.team or not source.alive
            or source.range != 1 or actual_hp <= 0 or not unit.alive):
        return
    awakened = _syn().is_awakened(unit, 'red_card')
    if inst.uses >= (4 if awakened else 2):
        return
    from arena_fields import move_unit
    moved = 0
    for _step in range(2):
        destination = battle._knock_cell(source, unit.pos)
        if destination is None or not source.alive:
            break
        move_unit(battle, source, destination, t, action_index, source=unit, reason='knockback')
        moved += 1
    if moved:
        fire(battle, inst, source, t, label='红牌', kind='move', value=moved)
        if awakened and source.alive:
            drained = min(source.energy, 25)
            source.energy -= drained
            battle._emit_state(source, t)
    else:
        inst.spend(t)


def _h_weakness(battle, inst, source, target, actual_hp, t, move=None, **_):
    unit = inst.unit
    if target is not unit or source is None or source.team == unit.team or actual_hp <= 0 or not unit.alive:
        return
    kind = (move or {}).get('type') or (source.piece.types[0] if source.piece.types else None)
    if kind is None or battle.dex.multiplier(kind, unit.piece.types) <= 1:
        return
    unit.attack = int(unit.attack * 1.3)
    unit.sp_attack = int(unit.sp_attack * 1.3)
    unit.haste_until, unit.haste_fraction = t + 5., max(unit.haste_fraction, .25)
    battle._emit_state(unit, t)
    fire(battle, inst, unit, t, label='弱点保险', kind='buff', camera='focus')


def _h_reaper(battle, inst, unit, killer, t, **_):
    owner = inst.unit
    if killer is not owner or not owner.alive or unit.team == owner.team:
        return
    gained = _d()._energy(battle, owner, 30)
    owner.haste_until, owner.haste_fraction = t + 3., max(owner.haste_fraction, .25)
    battle._emit_state(owner, t)
    fire(battle, inst, owner, t, label='逆鳞', kind='energy', value=gained)


def _h_whistle(battle, inst, unit, t, cast_index, **_):
    if unit is not inst.unit or not unit.alive:
        return
    hasted = 0
    for mate in battle.units:
        if mate.alive and mate.team == unit.team and _d()._dist(mate, unit) <= 2:
            mate.haste_until, mate.haste_fraction = t + 3., max(mate.haste_fraction, .20)
            hasted += 1
    if hasted:
        fire(battle, inst, unit, t, label='号令', kind='buff', value=hasted, spend=False)


def revival_save(battle, unit, t):
    """Called from arena_depth.prevent_death: an adjacent revival-seed holder saves ``unit``."""
    d = _d()
    for holder in battle.units:
        if (holder is unit or not holder.alive or holder.team != unit.team
                or not d.has_item(holder, 'revival_seed') or d._dist(holder, unit) > 1
                or 'revival_seed' in holder.threshold_used):
            continue
        holder.threshold_used.add('revival_seed')
        unit.hp = max(1, int(unit.max_hp * .25))
        cost = int(holder.max_hp * .15)
        holder.hp = max(1, holder.hp - cost)
        battle._emit_state(holder, t)
        battle._emit_state(unit, t)
        d._event(battle, holder, unit, 'revival_seed', t, 'item', '复活种子', 'heal', unit.hp,
                 team=unit.team, camera='focus')
        return True
    return False


def _spec(id, trigger, name, handler, **kw):
    return EffectSpec(id=id, source='item', trigger=trigger, name=name, description=MECH_ITEMS[id]['description'],
                      handler=handler, **kw)


UNIT_SPECS = (
    _spec('boomerang', 'basic_settled', '回旋镖', _h_boomerang),
    _spec('impact_gauntlet', 'basic_settled', '冲击护手', _h_impact),
    _spec('echo_bell', 'native_primary', '回响铃', _h_echo),
    _spec('flame_orb', 'basic_settled', '火焰宝珠', _status_on_basic('burn', '灼烧')),
    _spec('toxic_orb', 'basic_settled', '剧毒宝珠', _status_on_basic('poison', '剧毒')),
    _spec('static_glove', 'basic_settled', '静电手套', _h_static),
    _spec('taunt_bell', 'battle_start', '挑衅铃', _h_taunt_bell, limit=1),
    _spec('red_card', 'direct_hit', '红牌', _h_red_card),  # 2 uses (4 awakened), enforced in the handler
    _spec('weakness_policy', 'direct_hit', '弱点保险', _h_weakness, limit=1),
    _spec('reaper_scale', 'death', '逆鳞', _h_reaper, cooldown=1.),
    _spec('rally_whistle', 'native_cast', '号令哨', _h_whistle),
)


# ------------------------------------------------------------------ advisor data
# archetype, one-line playstyle, and links that make the item part of a plan.
# Each link: (id, text, test) where test(ctx) -> bool on the player's own pieces.
def _has_skill(ctx, *categories):
    return any(cat in categories for cat in ctx['skill_categories'])


def _tech(ctx, *keys):
    return any(key in ctx['techniques'] for key in keys)


def _bond(ctx, element, n):
    return ctx['bonds'].get(element, 0) >= n


GUIDE = {
    'boomerang': ('输出', '普攻弹射第二目标，攻速越快收益越高',
                  [('combo', '连击羁绊 / 节拍器叠攻速后，弹射次数跟着翻倍', lambda c: c['tactics'].get('bond_combo', 0) >= 2),
                   ('arc', '电 4 电弧也按普攻次数触发，与弹射一起清群', lambda c: _bond(c, 'ELECTRIC', 3))]),
    'impact_gauntlet': ('控制', '定期把目标推开，给岩钉和击退联动供能',
                        [('spikes', '队里有人铺岩钉：每次击退都会让敌人踩钉', lambda c: _has_skill(c, 'terrain') or _tech(c, 'stealth_rock')),
                         ('breach', '乘隙追击：击退后目标受伤 +12%', lambda c: 'breach_momentum' in c['augments']),
                         ('chime', '逐风鸣铃 / 潮汐甲壳在场：击退还能回能、加盾', lambda c: {'storm_chime', 'tide_shell'} & c['items'])]),
    'echo_bell': ('输出', '高威力单体本命追加 45% 回响',
                  [('quicken', '迅捷 / 心灵水晶加快施法，回响更频繁', lambda c: 'quicken' in c['mods'] or 'mind_crystal' in c['items']),
                   ('dragon', '龙威：本命命中后易伤，回响吃到加成', lambda c: c['tactics'].get('bond_dragon_pressure', 0) >= 1)]),
    'flame_orb': ('联动', '普攻点燃目标，是灼伤体系的发动机',
                  [('erosion', '侵蚀羁绊：灼伤跳伤三次给能量', lambda c: c['tactics'].get('bond_erosion', 0) >= 2),
                   ('spread', '扩散宝珠：把灼伤传给邻格', lambda c: 'contagion_orb' in c['items']),
                   ('burn_skill', '本命对灼伤目标有追加伤害（喷发 / 点火追击）', lambda c: c['burn_payoff'])]),
    'toxic_orb': ('联动', '普攻施毒，是毒系体系的发动机',
                  [('venom', '毒 4 毒蚀：中毒敌人受全队伤害 +12%', lambda c: _bond(c, 'POISON', 3)),
                   ('catalyst', '毒性催化：本命打中毒目标回能', lambda c: 'poison_catalyst' in c['augments']),
                   ('erosion', '侵蚀羁绊：中毒跳伤三次给能量', lambda c: c['tactics'].get('bond_erosion', 0) >= 2)]),
    'static_glove': ('控制', '定期麻痹目标，并为“打已控制目标”类本命开条件',
                     [('payoff', '队里有对麻痹 / 已控制目标追击的本命', lambda c: c['control_payoff'])]),
    'taunt_bell': ('坦克', '开局把火力拉到自己身上',
                   [('thorns', '反伤：钢 2 反甲 / 反震 / 毒甲让嘲讽变成输出', lambda c: _bond(c, 'STEEL', 2) or 'retaliate' in c['mods'] or 'thorns' in c['skill_categories']),
                    ('guard', '相邻防守型 + 护驾指令保护核心', lambda c: c['core'] is not None)]),
    'red_card': ('坦克', '被近战贴脸就把对方推开',
                 [('spikes', '岩钉铺场：推开的敌人会踩钉', lambda c: _has_skill(c, 'terrain') or _tech(c, 'stealth_rock')),
                  ('breach', '乘隙追击：推开后易伤', lambda c: 'breach_momentum' in c['augments'])]),
    'weakness_policy': ('输出', '被克制反而爆发：放在会被克制的输出位', []),
    'reaper_scale': ('输出', '击杀回能加速，收割手连杀滚雪球',
                     [('execute', '处决强化 / 斩首令提供稳定击杀', lambda c: 'execute' in c['mods'] or 'executioner' in c['augments'])]),
    'revival_seed': ('辅助', '贴着核心站，救下一次致命伤',
                     [('core', '与核心相邻时最有价值', lambda c: c['core'] is not None)]),
    'rally_whistle': ('辅助', '本命后全队加速，辅助施法越快越好',
                      [('support', '辅助型多：施法频繁', lambda c: c['roles'].count('support') >= 2)]),
}
# Existing v1/v2 items, so every obtainable item has an archetype in the advisor.
GUIDE_BASE = {
    'sash': ('坦克', '致命伤保留 1 生命：保护脆皮后排'), 'leftovers': ('坦克', '持续回复：承伤前排'),
    'healing_needle': ('控制', '命中封疗：压制对面治疗'), 'lucky_egg': ('经济', '每轮 +1 金'),
    'heart_bell': ('辅助', '治疗转护盾'), 'ward_bracer': ('坦克', '吸盾后强化普攻'),
    'clarity_charm': ('辅助', '净化后加盾'), 'contagion_orb': ('联动', '传播灼伤 / 中毒'),
    'metronome': ('输出', '同目标叠攻速'), 'heavy_boots': ('坦克', '免疫岩钉'),
    'trap_lens': ('联动', '岩钉伤害 +25%'), 'drain_fang': ('输出', '普攻吸血'),
    'tide_shell': ('坦克', '被击退后加盾'), 'dew_charm': ('辅助', '治疗溢出接力'),
    'torrent_orb': ('输出', '本命命中回能'), 'pulse_band': ('输出', '普攻充能'),
    'relay_coil': ('辅助', '充能后给盾'), 'grounding_cloak': ('坦克', '首次控制自动净化'),
    'storm_chime': ('联动', '击退后给队友回能'), 'life_orb': ('输出', '直接伤害 +20%，自损'),
    'damp_rock': ('联动', '雨天延长'), 'heat_rock': ('联动', '晴天延长'),
    'mind_crystal': ('输出', '施法返还能量'), 'quick_claw': ('输出', '开战 40 能量'),
    'escape_pack': ('坦克', '低血撤退加盾'), 'blast_core': ('坦克', '阵亡爆炸'),
}
ARCHETYPES = ('输出', '坦克', '控制', '联动', '辅助', '经济')
