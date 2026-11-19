"""Read-only interaction data for the /play prep moments (docs/62).

`build(sess)` is called while rendering an arena state. It only *reads* the
session: no RNG, no mutation, so battles and the arena golden digests are
unaffected. Every block explains itself with short human reasons so the UI can
show *why* (适配度、推荐携带者、可合成) instead of bare numbers.

Blocks
  augments  per pending reward: category, rarity, fit score/level, reasons,
            concrete changes, condition check (v1 conditional augments),
            rerolls left
  techniques per machine: category, compatible uids, best learner + reasons
  skills    per owned uid: native skill card (category, power, targeting, glyph)
            and pending star-up mod options with a short delta
  recipes   8x8 component matrix with craftable / missing / dead-pair cells
  equip     per finished item in the inventory: stat lines, recipe, ranked
            carriers (top 3) with reasons; per-unit free slots
"""
import arena
import arena_depth
import items as items_mod
import techniques as techniques_mod

ROLE_ZH = {'attack': '攻击型', 'defense': '防守型', 'support': '辅助型'}
CATEGORY_ZH = {'economy': '经济', 'rule': '规则', 'battle': '战斗', 'condition': '条件', 'growth': '成长'}
RARITY = {1: ('silver', '银'), 7: ('gold', '金'), 13: ('prismatic', '彩')}
SKILL_CATEGORY_ZH = {
    'drain': '吸取', 'area': '范围', 'displacement': '位移', 'cleanse': '净化', 'pursuit': '追击',
    'chain': '连锁', 'combo': '连击', 'heal': '治疗', 'energy': '充能', 'root': '定身', 'burst': '爆发',
    'poison': '施毒', 'shield': '护盾', 'terrain': '地形', 'vulnerability': '易伤', 'clear': '清场',
    'retaliation': '反击', 'control': '控制', 'taunt': '嘲讽', 'assassin': '刺杀', 'lifesteal': '吸血',
    'rescue': '救援', 'guard': '守护', 'execute': '处决', 'pierce': '贯穿',
}
SKILL_GLYPH = {
    'heal': '✚', 'lifesteal': '✚', 'drain': '✚', 'shield': '⛨', 'guard': '⛨', 'rescue': '⛨',
    'cleanse': '✧', 'energy': '⚡', 'poison': '☠', 'control': '❄', 'root': '❄', 'taunt': '◎',
    'area': '✺', 'chain': '⌁', 'burst': '✹', 'execute': '✕', 'assassin': '✕', 'pierce': '➶',
    'pursuit': '➶', 'displacement': '⇆', 'terrain': '▲', 'vulnerability': '↓', 'combo': '✦',
    'retaliation': '↺', 'clear': '✺',
}
TAG_ZH = {
    'items': '装备', 'stats': '数值', 'small_team': '小队', 'bonds': '羁绊', 'economy': '经济', 'stars': '升星',
    'melee': '近战', 'opening': '开局', 'frontline': '前排', 'ranged': '远程', 'sustain': '保命', 'aoe': '范围',
    'damage': '伤害', 'energy': '能量', 'positioning': '站位', 'poison': '中毒', 'support': '辅助',
    'shield': '护盾', 'knockback': '击退',
}
TARGETING_ZH = {'enemy': '敌方', 'ally': '友方', 'self': '自身', 'field': '场地'}
MOD_DELTA = {
    'amplify': '本命/技能机 伤害·治疗 +30%', 'spread': '主命中后 邻格 2 敌 35% 溅射',
    'execute': '目标 <15% 生命直接击倒', 'sustain': '回复实际伤害 30%',
    'fortify': '施放后 15% 护盾 3 秒', 'quake': '施放后 邻格敌人畏缩 0.6 秒',
    'retaliate': '施放后 4 秒反弹 30% 直接伤害', 'overflow': '施放后 2 名低血队友 8% 护盾',
    'quicken': '施放后返还 25 能量', 'sanctify': '施放后净化 1 名队友并减伤 25%',
}
ITEM_SPEC_TEXT = (
    ('atk', '攻击 / 特攻', '+{:.0%}'), ('speed', '攻速', '+{:.0%}'), ('ult_dmg', '技能伤害', '+{:.0%}'),
    ('dodge', '闪避', '{:.0%}'), ('dr', '减伤', '{:.0%}'), ('heal', '每秒回复最大生命', '{:.1%}'),
    ('healing_reduction', '命中封疗', '-{:.0%}'), ('gold_per_round', '每轮金币', '+{}'),
)
# Visible carrier policy for items outside arena_equipment.CRAFT_ORDER.
CLASSIC_FIT = {
    'choice_band': ({'attack': 3, 'support': 1}, '攻击 +35%：给主输出'),
    'swift_feather': ({'attack': 3, 'defense': 1}, '攻速 +25%：普攻越多越赚'),
    'focus_lens': ({'attack': 2, 'support': 2}, '技能伤害 +25%：本命输出位'),
    'sash': ({'attack': 2, 'support': 2, 'defense': 1}, '致命伤保留 1 生命：保护脆皮后排'),
    'leftovers': ({'defense': 3, 'support': 1}, '持续回复：承伤前排'),
    'bright_powder': ({'defense': 3, 'attack': 1}, '15% 闪避：被集火的前排'),
    'weather_stone': ({'defense': 3, 'support': 1}, '减伤：前排坦克'),
    'healing_needle': ({'attack': 3, 'defense': 1}, '命中封疗：压制对面治疗'),
    'lucky_egg': ({'support': 2, 'defense': 1, 'attack': 1}, '每轮 +1 金：谁带都一样，挑不打架的位置'),
    'mind_crystal': ({'support': 3, 'attack': 2}, '施放后返还能量：本命越强越赚'),
    'quick_claw': ({'attack': 3, 'support': 2}, '开战 40 能量：抢先手本命'),
    'escape_pack': ({'attack': 2, 'support': 2}, '低血撤退 + 护盾：保住后排'),
    'blast_core': ({'defense': 3, 'attack': 1}, '阵亡爆炸：放在会先倒的前排'),
}
SCARF_TYPES = {'scarf_fire': 'FIRE', 'scarf_water': 'WATER', 'scarf_electric': 'ELECTRIC'}
TYPE_ZH = {'FIRE': '火', 'WATER': '水', 'ELECTRIC': '电'}
ARENA_ITEM_REASON = {
    'relay_coil': '能量接力本命', 'dew_charm': '露水体质：回复联动', 'storm_chime': '风暴类本命 / 吼叫',
    'torrent_orb': '本命打敌人且有威力', 'drain_fang': '吸血：输出位最好', 'pulse_band': '攻击型叠层',
    'tide_shell': '防守型前排', 'grounding_cloak': '通用防护', 'damp_rock': '会求雨的携带者',
    'heat_rock': '会晴天的携带者', 'life_orb': '攻击型（尼多王强行最佳）', 'heart_bell': '治疗/吸血本命',
    'ward_bracer': '防守型或护盾本命', 'clarity_charm': '净化本命', 'contagion_orb': '施毒/灼伤携带者',
    'metronome': '攻击型普攻叠攻速', 'heavy_boots': '防守型踩岩钉', 'trap_lens': '地形本命 / 隐形岩',
}


def _skill(sid):
    from arena_skills import skill_of
    try:
        return skill_of(sid)
    except Exception:  # pragma: no cover - roster without arena skill
        return {}


def _pieces(seat):
    return [o.piece for o in seat.board] or [o.piece for o in seat.bench]


# ---------------------------------------------------------------- augments
def augment_category(key):
    spec = arena.ALL_AUGMENTS[key]
    tags = arena_depth.augment_tags(key)
    if key in arena.GROWTH_KEYS:
        return 'growth'
    if spec.get('scope') == 'economy' or 'economy' in tags:
        return 'economy'
    if str(spec.get('brief', '')).startswith('条件触发'):
        return 'condition'
    if arena_depth.AUGMENTS.get(key, {}).get('scope') == 'session':
        return 'rule'
    return 'battle'


def _team_skills(seat):
    return [(o, _skill(o.piece.species_id)) for o in (seat.board or seat.bench)]


def _condition(seat, key):
    """Whether the current team can trigger a v1 conditional augment at all."""
    team = _team_skills(seat)
    cats = [s.get('category') for _o, s in team]
    roles = [getattr(o.piece, 'role_key', 'attack') for o, _s in team]
    if key == 'poison_catalyst':
        n = sum(1 for o, s in team if s.get('category') == 'poison' or 'POISON' in o.piece.types)
        return n > 0, (f'{n} 名队员的本命能施毒' if n else '队里没有能施毒的本命')
    if key == 'watch_echo':
        healers = sum(1 for (o, s), role in zip(team, roles)
                      if role == 'support' and s.get('category') in ('heal', 'drain', 'lifesteal', 'rescue'))
        attackers = roles.count('attack')
        ok = healers > 0 and attackers > 0
        return ok, (f'{healers} 名治疗辅助 + {attackers} 名攻击型' if ok else '需要治疗型辅助和攻击型队友')
    if key == 'barrier_feedback':
        n = sum(1 for c in cats if c in ('shield', 'guard', 'rescue'))
        return n > 0, (f'{n} 名队员的本命会给护盾' if n else '没有给队友护盾的本命')
    if key == 'native_inspiration':
        n = cats.count('energy')
        return n > 0, (f'{n} 名队员的本命会给队友回能' if n else '没有给队友回能的本命')
    if key == 'breach_momentum':
        n = sum(1 for _o, s in team if s.get('category') == 'displacement' or '击退' in (s.get('tags') or []))
        return n > 0, (f'{n} 名队员的本命能击退' if n else '没有击退类本命')
    return None


def _bond_gains(seat):
    import arena_bonds
    counts = arena_bonds.count(_pieces(seat))
    gains = []
    for element, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n < 1:
            continue
        rule = arena_depth.BOND_RULES.get(element)
        note = f'（解锁{rule[2]}）' if rule and n + 1 == rule[0] else ''
        gains.append(f'{arena_bonds.TYPE_NAMES.get(element, element)} {n} → {n + 1}{note}')
    return gains[:3]


def _changes(sess, seat, key):
    import arena_session
    pop = seat.pop()
    gold = seat.gold
    if key in ('elite_squad', 'bond_resonance'):
        rows = [f'人口上限 {pop} → {pop - 1}']
        rows += ['全队生命、攻击 +22%'] if key == 'elite_squad' else _bond_gains(seat)
        return rows
    if key == 'dual_wield':
        learned = sum(1 for o in seat.all_pieces() if o.technique)
        return ['立即 +2 组件', '每只装备位 1 → 2'] + ([f'已学的 {learned} 台技能机战斗中失效'] if learned else [])
    if key == 'treasure_hunter':
        return ['立即 +2 组件', '野怪轮获胜再 +1 组件']
    if key == 'interest_master':
        return [f'利息上限 5 → 8（现有 {gold} 金：+{min(gold // 10, 5)} → +{min(gold // 10, 8)}）']
    if key == 'free_roll':
        cost = arena_session.refresh_cost(seat) if sess.is_depth else 2
        return [f'每轮前 2 次刷新免费（现在 {cost} 金/次）', '定向刷新 3 → 1 金']
    if key == 'salvage':
        return ['出售 2★/3★ 额外得 1 组件', f'拆解装备 {arena_session.DISMANTLE_COST} → 0 金']
    if key == 'fast_track':
        pairs = _fast_track_pairs(seat)
        return [f'现在有 {pairs} 对 1–2 费同星对子可自动补齐（每局 3 次）']
    if key == 'charge_horn':
        melee = sum(1 for o in seat.board if getattr(o.piece, 'distance', None) == arena.MELEE)
        return [f'{melee} 只近战开战冲锋，+20% 护盾 +15 能量']
    if key == 'vanguard':
        front = sum(1 for (r, _c) in seat.grid if r == 0)
        return [f'前排 {front} 名开战获得 20% 护盾']
    if key == 'sniper_nest':
        back = sum(1 for (r, _c), o in seat.grid.items()
                   if r == max(1, sess.grid_rows - 1) and getattr(o.piece, 'distance', None) != arena.MELEE)
        return [f'后排远程 {back} 名射程 +1、攻击 +10%']
    if key == 'xp_doctrine':
        return ['每轮开始 +1 经验（满 6 轮后 +2）']
    if key in arena.GROWTH_KEYS:
        left = max(0, 30 - sess.round_no)
        return [f'越早拿越强：现在第 {sess.round_no} 轮，最多再成长 {min(left, 12)} 轮']
    # Other augments: the card already shows the brief, so no duplicate "change" row.
    return []


def _fast_track_pairs(seat):
    groups = {}
    for o in seat.all_pieces():
        if getattr(o.piece, 'tier', 9) > 2:
            continue
        family = getattr(o.piece, 'family_id', o.piece.species_id)
        groups[(family, o.piece.star)] = groups.get((family, o.piece.star), 0) + 1
    return sum(1 for n in groups.values() if n == 2)


def _rule_reasons(sess, seat, key):
    """Readable fit notes for v2 rule augments whose tags the bot scorer ignores."""
    roles = [getattr(o.piece, 'role_key', 'attack') for o in (seat.board or seat.bench)]
    team = len(roles)
    if not team:
        return [{'text': '先招募伙伴，再看这条规则的适配度', 'good': False}]
    if key in ('giant_slayer', 'executioner'):
        n = roles.count('attack')
        return [{'text': f'{n} 名攻击型负责收割' if n else '没有攻击型来吃这条加成', 'good': n >= 2}]
    if key == 'chain_reaction':
        n = sum(1 for _o, s in _team_skills(seat) if s.get('category') in ('area', 'chain', 'burst', 'clear'))
        return [{'text': f'{n} 名队员有范围/连锁本命，敌人更容易连爆' if n else '缺少范围伤害，连爆要靠站位密集的对手',
                 'good': n > 0}]
    if key == 'undying':
        return [{'text': f'{team} 名队员中第一个倒下的会被救回一次', 'good': True}]
    if key == 'mana_siphon':
        adjacent = sum(1 for (r, c) in seat.grid if (r, c + 1) in seat.grid or (r + 1, c) in seat.grid)
        return [{'text': f'当前 {adjacent} 对相邻队友互相回能' if adjacent else '队员没有相邻站位，回能吃不到',
                 'good': adjacent >= 2}]
    if key == 'hold_the_line':
        ranged = sum(1 for o in (seat.board or seat.bench) if getattr(o.piece, 'distance', None) != arena.MELEE)
        return [{'text': f'{ranged} 名远程开战不必移动，减伤稳定' if ranged else '近战都要移动接敌，收益有限',
                 'good': ranged >= 2}]
    if key == 'elite_squad':
        return [{'text': f'当前上场 {len(seat.grid)} 名：人口少一格，换全队 +22%', 'good': len(seat.grid) >= 3}]
    if key == 'fast_track':
        pairs = _fast_track_pairs(seat)
        return [{'text': f'{pairs} 对低费同星对子马上能补齐' if pairs else '暂时没有可补齐的低费对子', 'good': pairs > 0}]
    return []


def augment_insight(sess, seat, key, signals=None):
    """Fit read-out for one augment against the seat's visible team."""
    value, reasons = arena.augment_fit(seat, key, signals)
    reasons = [{'text': text, 'good': good} for text, good in reasons]
    condition = _condition(seat, key)
    score = value
    if condition is not None:
        met, text = condition
        score += 2. if met else -.5
        reasons.insert(0, {'text': ('条件已满足：' if met else '条件未满足：') + text, 'good': met})
    spec = arena.ALL_AUGMENTS[key]
    category = augment_category(key)
    if not reasons and key in arena_depth.AUGMENTS:
        reasons.extend(_rule_reasons(sess, seat, key))
        score += sum(1. for row in reasons if row['good'])
    if not reasons:
        if spec.get('scope') == 'support':
            n = sum(1 for p in _pieces(seat) if getattr(p, 'role_key', '') == 'support')
            reasons.append({'text': f'{n} 名辅助型受益' if n else '队里还没有辅助型', 'good': n > 0})
            score += .5 if n else -.5
        elif category == 'growth':
            score += .5 if sess.round_no <= 7 else 0
            reasons.append({'text': '成长型：拿得越早叠得越多', 'good': sess.round_no <= 7})
        else:
            score += .5
            reasons.append({'text': '全队数值加成，任何阵容都生效', 'good': True})
    return {
        'id': key, 'category': category, 'category_name': CATEGORY_ZH[category],
        'tags': [TAG_ZH.get(tag, tag) for tag in arena_depth.augment_tags(key)],
        'score': round(score, 2),
        'reasons': reasons[:3],
        'changes': _changes(sess, seat, key),
        'condition': None if condition is None else {'met': condition[0], 'text': condition[1]},
    }


def augment_block(sess):
    p = sess.player
    signals = arena.augment_signals(p)
    rows = []
    for row in getattr(sess, 'arena_augments_pending', None) or []:
        try:
            tier = arena.AUGMENT_MILESTONES.index(row['round'])
        except ValueError:
            tier = 0
        rarity = RARITY.get(arena.AUGMENT_MILESTONES[tier], ('silver', '银'))
        options = [augment_insight(sess, p, option['id'], signals) for option in row['options']]
        best = max(option['score'] for option in options) if options else 0
        for option in options:
            option['fit'] = ('high' if option['score'] >= 2.75 or (option['score'] == best and best >= 2)
                             else 'mid' if option['score'] >= 1.5 else 'low')
            option['best'] = option['score'] == best
        rows.append({'id': row['id'], 'round': row['round'], 'rarity': rarity[0],
                     'rarity_name': rarity[1], 'rerolls_left': 0 if row.get('rerolled') else 1,
                     'options': options})
    # During prep last_battle is already cleared; the session keeps the rule
    # ledger of the latest settled battle in memory (not saved across reloads).
    last = getattr(sess, 'last_rule_ledger', None) or getattr(sess, 'last_battle', None) or {}
    ledger = [row for row in last.get('rows') or last.get('ledger') or []
              if row.get('team') == 0 and row.get('source') == 'augment']
    fields = ('triggers', 'damage', 'heal', 'shield', 'energy', 'prevented', 'estimated', 'idle', 'passive')
    selected = [{'id': key, 'category': augment_category(key),
                 'category_name': CATEGORY_ZH[augment_category(key)],
                 'last': {'round': last.get('round'),
                          'rows': [{k: row.get(k) for k in fields} for row in ledger if row.get('id') == key]}
                 if last else None}
                for key in arena._keys(p)]
    return {'pending': rows, 'selected': selected}


# ---------------------------------------------------------------- techniques
def technique_block(sess):
    p = sess.player
    ctx = arena.teaching_context(p.board)
    owned = p.all_pieces()
    rows = {}
    for t in arena.technique_catalog():
        key = t['id']
        compatible = [o for o in owned if techniques_mod.compatible_species(
            o.piece.species_id, key, ruleset=sess.ruleset)]
        candidates = [o for o in compatible if o.technique != key]
        # Highest fit first; ties follow the bots' learner preference (supports first).
        ranked = sorted(((arena.teaching_fit(ctx, o, key), o) for o in candidates),
                        key=lambda row: (-row[0][0], row[1].piece.role_key != 'support',
                                         row[1].piece.role_key == 'attack', row[1] not in p.board,
                                         row[1].piece.species_id))
        best = ranked[0] if ranked and ranked[0][0][0] > 0 else None
        rows[key] = {
            'category': techniques_mod.category_of(key),
            'category_name': arena._TM_CATEGORY_ZH.get(techniques_mod.category_of(key) or '', '通用'),
            'compatible': [o.uid for o in compatible],
            'known_by': [o.uid for o in owned if o.technique == key],
            'cost': t['cost'], 'count': p.inventory.techniques[key],
            'best': None if best is None else {
                'uid': best[1].uid, 'name': best[1].piece.name, 'score': best[0][0],
                'reasons': best[0][1][:2] or ['可以学习'],
                'replaces': (techniques_mod.view(best[1].technique)['name'] if best[1].technique else None)},
        }
    return rows


# ---------------------------------------------------------------- skills
def skill_block(sess):
    import arena_session
    p = sess.player
    rows = {}
    for o in p.all_pieces():
        s = _skill(o.piece.species_id)
        category = s.get('category')
        rows[o.uid] = {
            'category': category, 'category_name': SKILL_CATEGORY_ZH.get(category, category or '本命'),
            'glyph': SKILL_GLYPH.get(category, '✦'), 'power': s.get('power'),
            'targeting': s.get('targeting'), 'targeting_name': TARGETING_ZH.get(s.get('targeting'), ''),
            'behavior': s.get('behavior'), 'tags': list(s.get('tags') or []),
            'technique': (techniques_mod.view(o.technique)['name'] if o.technique else None),
            'mods': [{'id': key, 'name': arena_depth.MODS[key]['name'], 'delta': MOD_DELTA.get(key, ''),
                      'description': arena_depth.MODS[key]['description']}
                     for key in (row['id'] for row in arena_session.pending_mod_options(o))]
            if sess.is_depth else [],
        }
    return rows


# ---------------------------------------------------------------- items
def spec_lines(key):
    spec = items_mod.FINISHED.get(key, {})
    lines = []
    for field, label, fmt in ITEM_SPEC_TEXT:
        if isinstance(spec.get(field), (int, float)) and not isinstance(spec.get(field), bool):
            lines.append(f'{label} {fmt.format(spec[field])}')
    for element, bonus in (spec.get('type_dmg') or {}).items():
        lines.append(f'{TYPE_ZH.get(element, element)}系伤害 +{bonus:.0%}')
    if spec.get('sash'):
        lines.append('致命伤保留 1 生命（每场一次）')
    return lines


def _component_lines(sess, key):
    if not sess.is_depth:
        return []
    text = arena_depth.item_stats_text(key)
    return [part for part in text.split('、') if part]


def recipe_block(sess):
    p = sess.player
    stock = dict(p.inventory.components)
    catalog = items_mod.catalog(sess.ruleset)
    blocked = {'lucky_egg'} if items_mod.lucky_egg_count(sess.seats) >= items_mod.LUCKY_EGG_GLOBAL_CAP else set()
    order = items_mod.COMPONENT_ORDER
    cells = []
    for i, a in enumerate(order):
        for b in order[i:]:
            key = items_mod.craft_result(a, b, sess.ruleset)
            spec = catalog.get(key) if key != 'evo_stone' else None
            need = {a: 2} if a == b else {a: 1, b: 1}
            missing = [items_mod.COMPONENT_NAMES[c] for c, n in need.items() if stock.get(c, 0) < n
                       for _ in range(n - stock.get(c, 0))]
            cells.append({
                'a': a, 'b': b, 'item': key if spec else None, 'name': spec['name'] if spec else None,
                'depth': bool(spec and spec.get('depth_only')),
                'dead': spec is None,
                'craftable': bool(spec) and not missing and key not in blocked,
                'blocked': key in blocked,
                'missing': missing,
                'stats': _component_lines(sess, key) if spec else [],
                'effect': (spec.get('description') or '、'.join(spec_lines(key))) if spec else '',
            })
    return {'components': [{'key': c, 'name': items_mod.COMPONENT_NAMES[c], 'n': stock.get(c, 0),
                            'stats': _component_stat(sess, c)}
                           for c in order],
            'cells': cells}


def _component_stat(sess, component):
    if not sess.is_depth:
        return ''
    parts = []
    for stat, value in arena_depth.COMPONENT_STATS.get(component, {}).items():
        label = arena_depth.COMPONENT_STAT_TEXT[stat]
        parts.append(f'{label} +{value:g}' if stat == 'energy' else f'{label} +{value * 100:g}%')
    return '、'.join(parts)


def _carrier_score(owned, key):
    from arena_equipment import carrier_rank
    import arena_mech_items as mech
    piece = owned.piece
    role = getattr(piece, 'role_key', 'attack')
    if key in mech.MECH_ITEMS:
        rank = mech.carrier_rank(owned, key)
        if rank is None:
            return None, None
        return rank, f'{ROLE_ZH.get(role, role)} · {mech.GUIDE[key][1]}'
    rank = carrier_rank(owned, key)
    if rank is not None:
        return rank, f'{ROLE_ZH.get(role, role)} · {ARENA_ITEM_REASON.get(key, "适配")}'
    if key in SCARF_TYPES:
        element = SCARF_TYPES[key]
        if element in piece.types:
            return (3 if role == 'attack' else 2), f'{TYPE_ZH[element]}系{ROLE_ZH.get(role, role)} · 吃满 +30%'
        return None, None
    if key in CLASSIC_FIT:
        table, reason = CLASSIC_FIT[key]
        score = table.get(role)
        if score is None:
            return None, None
        ranged = getattr(piece, 'distance', None) != arena.MELEE
        if key == 'swift_feather' and ranged and role == 'attack':
            score += 1
            reason = '远程输出 · 吃满攻速'
        return score, f'{ROLE_ZH.get(role, role)} · {reason}'
    return None, None


def equip_block(sess):
    import arena_session
    p = sess.player
    owned = p.all_pieces()
    rows = {}
    for key in dict.fromkeys(p.inventory.finished):
        ranked = []
        for o in owned:
            score, reason = _carrier_score(o, key)
            if score is None:
                continue
            slots = arena_session.item_slots(o, p) if sess.is_depth else 1
            used = (1 if o.item else 0) + (1 if getattr(o, 'extra_item', None) else 0)
            on_board = o in p.board
            ranked.append({'uid': o.uid, 'name': o.piece.name, 'score': score + (0.5 if on_board else 0),
                           'reason': reason + ('' if on_board else ' · 在备战席'), 'free': used < slots})
        ranked.sort(key=lambda row: (-row['free'], -row['score'], row['name']))
        spec = items_mod.FINISHED.get(key, {})
        pair = arena_depth.recipe_components(key)
        rows[key] = {
            'name': spec.get('name', key), 'lines': spec_lines(key),
            'stats': _component_lines(sess, key),
            'effect': spec.get('description', ''),
            'recipe': ' + '.join(items_mod.COMPONENT_NAMES[c] for c in pair) if pair else '',
            'carriers': ranked[:3],
            'suits': ranked[0]['reason'].split(' · ', 1)[-1] if ranked else '',
        }
    slots = {}
    for o in owned:
        total = arena_session.item_slots(o, p) if sess.is_depth else 1
        held = [k for k in (o.item, getattr(o, 'extra_item', None)) if k]
        slots[o.uid] = {'total': total, 'used': len(held),
                        'items': [{'key': k, 'name': items_mod.FINISHED.get(k, {}).get('name', k),
                                   'lines': spec_lines(k), 'stats': _component_lines(sess, k)} for k in held]}
    return {'items': rows, 'slots': slots,
            'unequip_cost': arena_session.UNEQUIP_COST if sess.is_depth else 0}


# ---------------------------------------------------------------- item advisor
_BURN_PAYOFF = {'cinder_eruption'}
_CONTROL_PAYOFF = {'storm_conductor', 'charged_beacon', 'gale_cross', 'frost_kiss', 'horn_pressure',
                   'undertow_lock'}


def advisor_context(sess, seat=None):
    """What the player's own pieces, augments and items enable (public, own data only)."""
    import arena_bonds
    p = seat or sess.player
    owned = p.all_pieces()
    pieces = [o.piece for o in p.board] or [o.piece for o in owned]
    skills = [_skill(o.piece.species_id) for o in owned]
    counts = arena_bonds.count([o.piece for o in p.board]) if p.board else {}
    held = set(p.inventory.finished)
    for o in owned:
        held.update(k for k in (o.item, getattr(o, 'extra_item', None)) if k)
    traits = {getattr(o, 'arena_trait', None) for o in owned}
    return {
        'skill_categories': {s.get('category') for s in skills if s},
        'skill_ids': {s.get('effect', s.get('id')) for s in skills if s},
        'techniques': {o.technique for o in owned if o.technique},
        'augments': set(__import__('arena_session').augment_keys(p)),
        'bonds': {k: v for k, v in counts.items() if k.isupper()},
        'tactics': {k: v for k, v in counts.items() if k.startswith('bond_')},
        'items': held,
        'mods': {m for o in owned for m in (getattr(o, 'skill_mods', None) or [])},
        'roles': [getattr(piece, 'role_key', 'attack') for piece in pieces],
        'core': next((o for o in owned if getattr(o, 'is_core', False)), None),
        'burn_payoff': bool(_BURN_PAYOFF & {s.get('effect', s.get('id')) for s in skills if s})
                       or 'trait_ignite_pursuit' in traits,
        'control_payoff': bool(_CONTROL_PAYOFF & {s.get('effect', s.get('id')) for s in skills if s}),
    }


def item_guide(sess, key, ctx):
    import arena_mech_items as mech
    spec = items_mod.FINISHED.get(key, {})
    if key in mech.GUIDE:
        archetype, playstyle, links = mech.GUIDE[key]
    else:
        archetype, playstyle = mech.GUIDE_BASE.get(key, ('输出' if spec.get('atk') else '坦克', ''))
        links = []
    active, missing = [], []
    for _id, text, test in links:
        try:
            (active if test(ctx) else missing).append(text)
        except Exception:  # pragma: no cover - defensive on partial seats
            missing.append(text)
    return {'archetype': archetype, 'playstyle': playstyle, 'active': active, 'missing': missing,
            'mechanic': key in mech.MECH_ITEMS or bool(spec.get('description')),
            'treasure': bool(spec.get('treasure'))}


def advice_block(sess):
    """Concrete next steps: equip what you hold, craft what you can, chase one component."""
    if not sess.is_arena:
        return None
    import arena_session
    p = sess.player
    ctx = advisor_context(sess)
    owned = p.all_pieces()
    catalog = items_mod.catalog(sess.ruleset)

    def best(key):
        ranked = []
        for o in owned:
            score, reason = _carrier_score(o, key)
            if score is None:
                continue
            slots = arena_session.item_slots(o, p) if sess.is_depth else 1
            used = (1 if o.item else 0) + (1 if getattr(o, 'extra_item', None) else 0)
            if used >= slots:
                continue
            ranked.append((score + (0.5 if o in p.board else 0) + (0.5 if getattr(o, 'is_core', False) else 0),
                           o, reason))
        ranked.sort(key=lambda row: (-row[0], row[1].piece.name))
        return ranked[0] if ranked else None

    def score_item(key):
        guide = item_guide(sess, key, ctx)
        carrier = best(key)
        value = (carrier[0] if carrier else 0) + 1.5 * len(guide['active']) + (1 if guide['mechanic'] else 0)
        return value, guide, carrier

    suggestions = []
    for key in dict.fromkeys(p.inventory.finished):
        if key in ('lucky_egg', 'evo_stone'):
            continue
        value, guide, carrier = score_item(key)
        if carrier:
            suggestions.append({'action': 'equip', 'item': key, 'name': catalog.get(key, {}).get('name', key),
                                'uid': carrier[1].uid, 'unit': carrier[1].piece.name, 'value': round(value, 1),
                                'why': [carrier[2].split(' · ', 1)[-1]] + guide['active'][:2],
                                'archetype': guide['archetype']})
    stock = dict(p.inventory.components)
    order = items_mod.COMPONENT_ORDER
    for i, a in enumerate(order):
        for b in order[i:]:
            key = items_mod.craft_result(a, b, sess.ruleset)
            if key == 'evo_stone' or key not in catalog or key == 'lucky_egg':
                continue
            need = {a: 2} if a == b else {a: 1, b: 1}
            short = sum(max(0, n - stock.get(c, 0)) for c, n in need.items())
            if short > 1:
                continue
            value, guide, carrier = score_item(key)
            if not carrier:
                continue
            row = {'item': key, 'name': catalog[key]['name'], 'uid': carrier[1].uid, 'unit': carrier[1].piece.name,
                   'recipe': [items_mod.COMPONENT_NAMES[a], items_mod.COMPONENT_NAMES[b]],
                   'value': round(value - (1 if short else 0), 1),
                   'why': [carrier[2].split(' · ', 1)[-1]] + guide['active'][:2], 'archetype': guide['archetype']}
            if short == 0:
                suggestions.append({**row, 'action': 'craft'})
            else:
                lacking = next(items_mod.COMPONENT_NAMES[c] for c, n in need.items() if stock.get(c, 0) < n)
                suggestions.append({**row, 'action': 'chase', 'lacking': lacking})
    seen, unique = set(), []
    for row in sorted(suggestions, key=lambda r: (-r['value'], {'equip': 0, 'craft': 1, 'chase': 2}[r['action']])):
        if (row['action'], row['item']) in seen:
            continue
        seen.add((row['action'], row['item']))
        unique.append(row)
    guides = {key: item_guide(sess, key, ctx) for key in catalog
              if key not in ('evo_stone',) and not items_mod.retired(key, sess.ruleset)}
    archetypes = {}
    for o in owned:
        for k in (o.item, getattr(o, 'extra_item', None)):
            if k:
                arche = guides.get(k, {}).get('archetype')
                if arche:
                    archetypes[arche] = archetypes.get(arche, 0) + 1
    return {'suggestions': unique[:6], 'guides': guides, 'team_archetypes': archetypes,
            'archetype_order': list(__import__('arena_mech_items').ARCHETYPES)}


def build(sess):
    return {
        'item_advice': advice_block(sess),
        'version': 1,
        'augments': augment_block(sess),
        'techniques': technique_block(sess),
        'skills': skill_block(sess),
        'recipes': recipe_block(sess),
        'equip': equip_block(sess),
    }
