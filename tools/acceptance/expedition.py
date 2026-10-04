"""Application bridge: game-specific loadouts and an idempotent profile outbox.

Session durability precedes profile writes. A failed profile write never rolls
back a committed battle; resume/state replays the same cumulative run snapshot.
All callers hold demo._LOCK. Neither this module nor the codec owns storage policy.
"""
import copy
import hashlib
import json
import re

import metagame
import partners
from data import pokedex
from meta_profile import ProfileStore


def store():
    import demo
    return ProfileStore(demo.SAVE_ROOT)


def configure(session, params):
    import demo
    mode = params.get('mode', 'classic')
    if mode not in ('classic', 'expedition'):
        raise demo.DemoError('未知对局模式')
    if mode == 'classic':
        return
    profile = metagame.view(store().load())
    partner = int(params.get('partner', 6))
    technique = params.get('technique') or None
    item = params.get('item') or None
    if technique == 'none':
        technique = None
    if item == 'none':
        item = None
    loadout = partners.validate_loadout(partner, technique)
    if partner not in profile['partner_ids']:
        raise demo.DemoError('该主搭档尚未解锁')
    if technique and technique not in profile['technique_ids']:
        raise demo.DemoError('该招式机器尚未解锁')
    if item and item not in profile['item_ids']:
        raise demo.DemoError('该开局装备尚未解锁')
    session.expedition = {**loadout, 'item': item}


def deploy_starter(session):
    if session.expedition is None:
        return
    import demo
    partner = next(p for p in partners.catalog() if p['id'] == session.expedition['partner'])
    sid = min(partner['family_ids'])
    template = session.templates[sid]
    # Starter is bought at its ordinary shop cost; no free sellable currency.
    if session.pool.remaining[sid] < 1 or session.player.gold < template.tier:
        raise demo.DemoError('开局搭档无法购买，请更换种子')
    session.pool.take(sid)
    owned = demo.shop_mod.OwnedPiece(template, template.tier)
    owned.item = session.expedition['item']
    owned.technique = session.expedition['technique']
    session.expedition['technique'] = None  # 教学属于这只棋子，不再复制给后来买到的搭档。
    session.player.gold -= template.tier
    session.player.grid[(0, 2)] = owned
    session._say(f"主搭档：{template.name}（-{template.tier} 金）；进化后保留搭档特性")


def sync_profile(session):
    try:
        saved = store().load()
        updated = metagame.apply_progress(saved, session.progress_snapshot())
        if saved != updated:
            store().save(updated)
        session.profile_warning = None
    except Exception as exc:
        session.profile_warning = f'对局已保存，档案同步待重试：{exc}。继续存档会重试。'


def status(session):
    if session.expedition is None:
        return None
    info = next(p for p in partners.catalog() if p['id'] == session.expedition['partner'])
    deployed = next((o for o in session.player.board
                     if o.piece.species_id in info['family_ids']), None)
    technique = next((t for t in partners.techniques_catalog()
                      if deployed and t['id'] == deployed.technique), None)
    return {'partner': info['name'], 'trait': info['trait_name'],
            'description': info['trait_description'],
            'active': deployed.piece.name if deployed else None,
            'technique': technique, 'stat_mode': 'budget_v1',
            'run_id': session.run_id}


def api_profile():
    import demo
    with demo._LOCK:
        try:
            view = metagame.view(store().load())
            templates = demo.build_templates()
            species = pokedex().species
            entries = []
            for p in partners.catalog():
                entries.append({'id': p['id'], 'name': p['name'],
                                'starter_name': templates[min(p['family_ids'])].name,
                                'cost': templates[min(p['family_ids'])].tier,
                                'description': p['trait_name'] + '：' + p['trait_description'],
                                'unlocked': p['id'] in view['partner_ids'],
                                'techniques': p['techniques']})
            techniques = [{**t, 'unlocked': t['id'] in view['technique_ids']}
                          for t in partners.techniques_catalog()]
            item_keys = ('leftovers', 'sash')
            items = [{'id': k, 'name': demo.items_mod.FINISHED[k]['name'],
                      'description': demo._item_effect(k), 'unlocked': k in view['item_ids']}
                     for k in item_keys]
            challenges = [{**c, 'progress': c['current'],
                           'rewards': [r['name'] for r in c['rewards']]}
                          for c in view['challenges']]
            collection = [{'id': sid, 'name': species.get(sid, {}).get('name_zh', f'#{sid}'),
                           **{k: sid in view['dex'][k] for k in ('seen', 'fielded', 'won')}}
                          for sid in sorted(set(templates) | set(view['dex']['seen']))]
            return {'ok': True, 'stats': view['stats'], 'challenges': challenges,
                    'partners': entries, 'techniques': techniques, 'items': items,
                    'dex': collection}
        except Exception as exc:
            return {'ok': False, 'error': f'档案读取失败，原文件未覆盖：{exc}'}


def decode_extension(state, data):
    extension = data.get('expedition_state')
    if 'expedition_state' not in data:
        # Stable across imports into different save slots; a legacy run has no
        # historic observations, so do not invent battle achievements.
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        state.run_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
        state.observe()
        return
    if not isinstance(extension, dict) or set(extension) != {'run_id', 'loadout', 'discoveries'}:
        raise ValueError('远征存档字段无效')
    run_id = extension['run_id']
    if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('无效的对局永久编号')
    loadout = extension['loadout']
    if loadout is not None:
        if not isinstance(loadout, dict) or set(loadout) != {'partner', 'technique', 'item'}:
            raise ValueError('远征配置字段无效')
        if type(loadout['partner']) is not int:
            raise ValueError('主搭档编号必须是整数')
        if partners.validate_loadout(loadout['partner'], loadout['technique']) is None:
            raise ValueError('远征配置缺少主搭档')
        if loadout['item'] not in (None, 'leftovers', 'sash'):
            raise ValueError('无效的开局装备')
    discoveries = extension['discoveries']
    if not isinstance(discoveries, dict) or set(discoveries) != {'seen', 'fielded', 'won'}:
        raise ValueError('图鉴进度字段无效')
    state.run_id, state.expedition = run_id, copy.deepcopy(loadout)
    state.discoveries = copy.deepcopy(discoveries)
    # Reuse exactly the profile's strict observation validation on import.
    metagame.apply_progress(metagame.initial_profile(), state.progress_snapshot())


def import_profile(raw, inspect_only=False):
    import demo
    with demo._LOCK:
        try:
            saved = store()
            profile = saved.inspect_backup(raw) if inspect_only else saved.import_backup(raw)
            return {'ok': True, 'stats': metagame.view(profile)['stats']}
        except Exception as exc:
            return {'ok': False, 'error': f'档案导入未完成，请重新读取核对：{exc}'}
