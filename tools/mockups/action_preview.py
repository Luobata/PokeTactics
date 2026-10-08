"""Shared action inventory and real-event clip selection for editor and checks."""
from dataclasses import asdict
from animation_timeline import native_targeting

PREVIEW_ACTIONS = {
    'idle': '待机', 'move': '移动', 'attack': '普通攻击',
    'cast': '大招', 'hit': '受击', 'death': '退场',
}


def describe_clip(anim, kind):
    """Select a bounded window on the existing presentation timeline.

    No action, damage or death is synthesized. `subject` is the unit whose
    snapshots are shown: recipient for attacks/casts, selected actor otherwise.
    Idle is an explicitly quiet window in a delayed-action training fixture.
    """
    if kind not in PREVIEW_ACTIONS:
        raise ValueError(f'unsupported preview action: {kind}')
    action, source_index, subject = None, None, 0
    targeting = 'enemy'
    if kind in ('attack', 'cast', 'hit'):
        candidates = [a for a in anim.timeline.actions if not a.secondary and
                      (a.target == 0 if kind == 'hit' else a.attacker == 0 and a.kind == kind)]
        positive = [a for a in candidates if anim.events[a.source_index][6 if a.kind == 'cast' else 4] > 0]
        action = next(iter(positive or candidates), None)
        if action is None or (kind == 'hit' and not positive):
            raise ValueError(f'本种子没有产生真实{PREVIEW_ACTIONS[kind]}事件')
        source_index, subject = action.source_index, action.target
        targeting = native_targeting(anim.events[source_index], anim.by_idx) if kind == 'cast' else 'enemy'
        before, at = action.impact-.001, action.impact
        if kind == 'hit':
            start, end = max(0., action.impact-.2), action.impact+.7
            phases = [('受击前', start), ('命中', at), ('恢复', at+.3)]
        else:
            start, end = max(0., action.start-.25), max(action.impact+.95, action.recover_end+.25)
            phases = [('开始', action.start), ('释放', action.release),
                      ('命中' if targeting == 'enemy' else '生效', at), ('恢复结束', action.recover_end)]
    elif kind in ('move', 'death'):
        event_kind = 'move' if kind == 'move' else 'die'
        events = [ev for ev in anim.timeline.events if ev[1] == event_kind and ev[2] == 0]
        event = next(iter([ev for ev in events if ev[0] >= .35] or events), None)
        if event is None:
            raise ValueError(f'本种子没有产生真实{PREVIEW_ACTIONS[kind]}事件')
        at = event[0]
        before = max(0., at-.001)
        if kind == 'move':
            from render_battle_gif import MOVE_SMOOTH
            finish = at+MOVE_SMOOTH
            phases = [('起步', at), ('途中', (at+finish)/2), ('到位', finish)]
        else:
            from motion import species_motion, duration
            sid = anim.by_idx[0].piece.species_id
            finish = at+(duration(sid, 'death') if sid in species_motion else .6)
            phases = [('倒下', at), ('消散', (at+finish)/2), ('离场', finish+.05)]
        start, end = max(0., at-.2), finish+.25
    else:
        start, end = .4, 1.6
        before, at = start, end
        phases = [('循环开始', start), ('呼吸', 1.), ('循环结束', end)]
    return {'kind': kind, 'targeting': targeting, 'action': asdict(action) if action else None,
            'source_index': source_index, 'clip_start': start, 'clip_end': end,
            'phases': [{'label': label, 'at': round(t, 6)} for label, t in phases],
            'subject': {'unit': subject, 'name': anim.by_idx[subject].piece.name},
            'snapshot_before': before, 'snapshot_at': at,
            'training_scene': 'precharged_skill' if kind == 'cast' else
                              'delayed_action_idle' if kind == 'idle' else 'stationary_posts'}


def action_coverage(sid, rig, authored, can_cast):
    """Report authored work separately from fallback support and pending work."""
    body = 'authored_pose' if authored else 'procedural'
    result = {}
    for action, label in PREVIEW_ACTIONS.items():
        parts = bool(rig.get('implemented') and rig.get('actions', {}).get(action))
        result[action] = {'label': label, 'supported': can_cast if action == 'cast' else True,
                          'body': body, 'parts': 'authored' if parts else 'none',
                          'preview': True}
    # These are real shared rendering paths, not six bespoke species animations.
    result['status'] = {'label': '状态与增益', 'supported': True, 'body': 'shared_overlay',
                        'parts': 'none', 'preview': False,
                        'note': '共享冰冻定格、状态图标、染色和增益环；没有独立物种动作'}
    result['entry'] = {'label': '入场', 'supported': True, 'body': 'shared_intro',
                       'parts': 'none', 'preview': False, 'note': '共享开场演出，没有独立角色入场片段'}
    result['victory'] = {'label': '胜利', 'supported': False, 'body': 'pending',
                         'parts': 'none', 'preview': False, 'note': '尚无独立胜利动作'}
    return result
