"""Shared navigation and session-free reference data for the local game portal."""

import re
from html import escape
from urllib.parse import quote


NAV_LINKS = (("/", "营地首页"), ("/play", "游戏试玩"),
             ("/pokedex", "战术图鉴"), ("/guide", "玩法指南"),
             ("/tools", "调试工具"))
PORTAL_ROUTES = ("/", "/pokedex", "/guide", "/tools")


def wrap_page(page, path):
    """Add the same navigation without changing any page scripts or game state."""
    if 'aria-label="全站导航"' in page:
        return page
    path = path.rstrip('/') or '/'
    active = path if path in dict(NAV_LINKS) else '/tools'
    links = ''.join(
        f'<a href="{url}"' + (' aria-current="page"' if url == active else '')
        + f'>{label}</a>' for url, label in NAV_LINKS)
    nav = ('<nav class="portal-nav" aria-label="全站导航">'
           '<a class="portal-brand" href="/" aria-label="PokeTactics 营地首页">'
           '<span class="portal-ball" aria-hidden="true"></span>'
           'POKÉ<span>TACTICS</span></a>'
           f'<div class="portal-links">{links}</div></nav>')
    legacy = {
        '/demo': ('经典试玩', '/play', '当前竞技试玩'),
        '/roster': ('经典 84 种棋子库', '/pokedex', '竞技精灵图鉴'),
        '/items': ('经典装备参数', '/pokedex?tab=items', '竞技道具与合成图'),
        '/synergy': ('经典属性羁绊', '/pokedex?tab=bonds', '竞技羁绊目录'),
        '/match': ('经典规则单局模拟', '/scenarios?mode=arena', '竞技战斗场景'),
        '/experiments': ('经典规则对照实验', '/scenarios?mode=arena', '竞技联动场景'),
        '/device': ('240 × 320 设备工具', '/anim?mode=arena', '竞技战斗预览'),
        '/expedition': ('设备远征工具', '/play', '竞技试玩'),
    }
    if path in legacy:
        label, destination, current = legacy[path]
        nav += ('<aside class="portal-version-note" style="padding:10px 24px;'
                'background:#e6e7d7;border-bottom:1px solid #b9c5ae;color:#42533b;'
                'font:13px/1.6 system-ui">'
                f'<strong>{label}</strong> · 保留用于经典 / 设备回归。'
                f'<a href="{destination}" style="color:inherit;margin-left:12px">打开{current} →</a></aside>')
    assets = '<link rel="stylesheet" href="/hub/assets/portal.css">'
    if 'name="viewport"' not in page and 'name=viewport' not in page:
        assets += '<meta name="viewport" content="width=device-width,initial-scale=1">'
    if '</head>' in page:
        page = page.replace('</head>', assets + '</head>', 1)
    else:
        page = re.sub(r'</title>', '</title>' + assets, page, count=1)
    classes = 'portal-page ' + ('portal-play' if path == '/play' else
                               'portal-tool-page' if active == '/tools' and path != '/tools'
                               else 'portal-hub-page')
    body = re.search(r'<body\b[^>]*>', page, flags=re.I)
    if body:
        tag = body.group()
        class_attr = re.search(r'''\bclass=(?:"([^"]*)"|'([^']*)'|([^\s>]*))''', tag)
        if class_attr:
            existing = next(value for value in class_attr.groups() if value is not None)
            tag = tag[:class_attr.start()] + f'class="{existing} {classes}"' + tag[class_attr.end():]
        else:
            tag = tag[:-1] + f' class="{classes}">'
        page = page[:body.start()] + tag + nav + page[body.end():]
    else:
        # The older console templates omit body/head closing tags.
        page = page.replace('<main', f'<body class="{classes}">{nav}<main', 1)
    return page


def catalog_view(demo):
    """Use the trial's authoritative definitions, never allocate a Session."""
    arena = demo.arena_mod
    import catalog_advice as advice
    import arena_bonds
    import arena_traits
    import copy
    items = demo.items_mod
    item_views = [{
        'id': key, 'name': spec['name'],
        'description': demo._item_effect(key, 'budget_v1'),
        'recipes': [[{'id': part, 'name': items.COMPONENT_NAMES[part]} for part in pair]
                    for pair in spec['pairs'] or ()],
        'source': ('组件合成；不在回合战利品池中' if key == 'lucky_egg'
                   else '组件合成 / 小回合随机战利品'),
        'slot': '每只精灵一个装备位，可卸下转移',
        'global_cap': items.LUCKY_EGG_GLOBAL_CAP if key == 'lucky_egg' else None,
        'copy_rule': (f'全场同时最多 {items.LUCKY_EGG_GLOBAL_CAP} 件，包含所有训练家已装备与仓库中的幸运蛋'
                      if key == 'lucky_egg' else '可重复合成或获得；多名精灵可各装备一件同名道具'),
        **copy.deepcopy(advice.ITEMS.get(key, {})),
    } for key, spec in items.catalog(arena.RULESET).items()]
    pokemon_views = []
    for sid, piece in arena.build_templates().items():
        generation = 2 if sid in arena.GEN2_ROSTER else 1
        pool_group = ('第二世代精灵' if generation == 2 else
                      '第一世代独立精灵' if sid in arena.EXPANSION_ROSTER else '进化形态')
        pokemon_views.append({**demo._piece_view(piece, ruleset=arena.RULESET),
                              'cost': piece.tier, 'pool_total': arena.pool_cap(sid),
                              'generation': generation,
                              'generation_name': '第二世代' if generation == 2 else '第一世代',
                              'pool_group': pool_group,
                              'bonds': arena_bonds.memberships(sid)})
    build_views = copy.deepcopy(advice.BUILDS)
    for build in build_views:
        build['base_stage']['bonds'] = arena_bonds.preparation(build['base_stage']['members'])
        if build.get('transition'):
            build['transition']['bonds'] = arena_bonds.preparation(build['transition']['members'])
    return {'ok': True,
            'ruleset': arena.RULESET,
            'pokemon': pokemon_views,
            'bonds': arena_bonds.catalog(),
            'traits': arena_traits.catalog(),
            'trait_rules': {
                'covered_species': sum(bool(row.get('trait')) for row in pokemon_views),
                'available_traits': len(arena_traits.catalog()),
                'roster_species': len(pokemon_views),
                'fixed_by_species': False, 'random_unlock': False,
                'mutually_exclusive': True, 'choice_phase': 'prep', 'choice_cost': 0,
                'occupies_skill_slot': False,
                'description': '竞技特性满足条件时自动触发，不消耗能量，也不占本命或学习位。尼多王、水箭龟可在准备期免费切换各自两项互斥特性；大竺葵的第二特性需完成竞技挑战「羁绊编织者」解锁，其他精灵保留固定特性。',
                'coverage_note': (f"本版覆盖{covered}位精灵，共{len(arena_traits.catalog())}项特性；"
                                  '其余精灵尚未配置，不会随机获得特性。'
                                  if (covered := sum(bool(row.get('trait')) for row in pokemon_views)) < len(pokemon_views)
                                  else f"本版48位竞技精灵全部拥有特性，共{len(arena_traits.catalog())}项特性；特性不会随机获得，始终跟随物种。"),
            },
            'techniques': arena.technique_catalog(),
            'items': item_views,
            'equipment_rules': {
                'slots_per_pokemon': 1, 'duplicates_allowed': True,
                'lucky_egg_global_cap': items.LUCKY_EGG_GLOBAL_CAP,
                'lucky_egg_count_includes_inventory': True,
                'lucky_egg_in_round_loot': False,
                'unlisted_pairs_craftable': False,
                'description': '普通装备可重复获得和合成，多只精灵可以分别携带同名装备；每只精灵只有一个装备位。',
                'exception': (f'幸运蛋为经济装备，全场同时最多 {items.LUCKY_EGG_GLOBAL_CAP} 件'
                              '（所有训练家已装备与仓库合计），只能合成，不在回合战利品池中。'),
            },
            'components': [{'id': key, 'name': items.COMPONENT_NAMES[key],
                            'source': '小回合随机战利品；第3、6轮结算额外组件八选一',
                            'recipes': [row['id'] for row in item_views
                                        if any(key == part['id'] for pair in row['recipes'] for part in pair)]}
                           for key in items.COMPONENT_ORDER],
            'augments': [{**arena.augment_view(key), **copy.deepcopy(advice.AUGMENTS.get(key, {})),
                          'source': ('完成竞技挑战后进入候选池；机器人永远从基础池抽取'
                                     if key in arena.AUGMENT_LOCKS else
                                     '第 1、7、13 轮，从三个选项中选择一个；同一强化不能重复选择'),
                          **({'unlock_challenge': arena.AUGMENT_LOCKS[key]} if key in arena.AUGMENT_LOCKS else {}),
                          'scope': '本局全队生效'} for key in arena.AUGMENTS],
            'technique_advice': copy.deepcopy(advice.TECHNIQUES),
            'builds': build_views}


def document_view(relative, source):
    """Keep engineering documents and report source in the same navigation."""
    title = next((line.lstrip('# ').strip() for line in source.splitlines()
                  if line.startswith('# ')), relative)
    category = '设计文档' if relative.startswith('docs/') else '验证报告'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · PokeTactics</title></head><body class="portal-reference-page">
<main class="portal-document"><a href="/tools">← 返回调试工具</a>
<p class="document-category">{category} / 文档原文</p><h1>{escape(title)}</h1>
<p class="document-note">设计与工程参考。当前竞技玩法请查看 <a href="/guide">玩法指南</a>。
<a href="/{quote(relative)}" download>下载 Markdown 原文 ↓</a></p>
<pre>{escape(source)}</pre></main></body></html>'''
