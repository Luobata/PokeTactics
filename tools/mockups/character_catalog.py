"""Player-facing character identity, grounded in the active combat and rig data."""
from character_rigs import catalog as rig_catalog
from profiles import get as profile_of
from data import pokedex

# Tactical intent is presentation data. Damage, targets, ranges and action tracks
# continue to come from the simulator/rig definitions, never from these strings.
TACTICS = {
    6: ("打击抱团后排", "分散站位，避免多人紧贴主目标。", "抬爪助力火弹", "展翼蓄火，从口部喷射火焰"),
    9: ("打穿纵向阵线，打乱前排", "错开前后排，边界或占用格会阻止击退。", "双炮短促后坐", "炮筒蓄压、贯穿水柱、主目标后退"),
    3: ("靠近前排提供续航", "拉开治疗距离；满血队伍无法储存溢出治疗。", "左右藤鞭伸展回收", "花盘聚光，日光束命中后回流治疗"),
    26: ("惩罚相距较近的多个敌人", "分散超过跳跃距离；地面免疫可截断电链。", "电火花", "十万伏特在相邻目标间跳跃"),
    65: ("切入生命最低的敌人", "保护残血角色周围的落点；胡地切入后较脆。", "念力弹", "消失、瞬移落位、精神强念"),
    94: ("干扰敌人大招节奏", "低能量目标可供偷取的能量较少；一般系免疫舌舔。", "幽灵波动", "舌舔命中后，将偷取的能量拉回自身"),
    76: ("在接敌处震击多人", "避免围住隆隆岩；飞行系免疫地震。", "岩石重击", "地面裂纹扩散，邻格受击与短暂畏缩"),
    143: ("前排承伤与自我续航", "保持距离减少邻格波及；集中伤害压过自愈。", "重拳", "蓄力光束、近身震荡、自愈"),
}


# Content can be promoted independently: mechanics, body, parts and effects are
# separate capabilities. A species never needs to appear in TACTICS to play.
GENERIC_TACTICS = {
    "double_strike": ("主命中后追加一次 45% 伤害", "压低单体血量", "用高防单位承接连续攻击。"),
    "charge": ("施法前向目标突进，最多两格", "缩短接敌距离", "用前排限制突进落点。"),
    "heavy_blow": ("命中后将目标击退一格，有空格才生效", "打乱敌人阵形", "利用边界或占用格阻止击退。"),
    "volley_shot": ("主命中外，追加攻击最近两名敌人，各 40% 伤害", "同时压低多个敌人的血量", "多名承伤单位分担散射。"),
    "bulwark": ("施法后自身获得 3 秒 35% 减伤", "前排持续承伤", "减伤结束后集中输出。"),
    "mend": ("施法时回复自身最大生命的 20%", "前排自我续航", "集中伤害压过回复。"),
}


def character_catalog(*, mode='classic', pieces=None, asset_root=None):
    """JSON-safe capability catalog for the active roster, with no ID allowlist.

    Optional inputs let exporters validate the exact asset pack being shipped.
    Missing art is reported separately from simulation/skill readiness.
    """
    from presentation_modes import mode_info, normalize_mode
    mode = normalize_mode(mode)
    if mode == 'arena':
        return _arena_catalog(pieces=pieces, asset_root=asset_root)
    from pathlib import Path
    from roster import build_roster
    from skills import skill_of, resolve_cast, GENERIC_DESCRIPTIONS
    from profiles import effective_range
    from motion import species_motion, validate_motion
    from skill_vfx import AUTHORED_SKILLS
    from move_effects import SUPPORTED_SPECIES
    from action_preview import action_coverage, PREVIEW_ACTIONS
    from decoders import Front, Palettes, POKEWALK
    root = Path(asset_root) if asset_root is not None else POKEWALK
    front, palettes = Front(root / "gen1_front.bin"), Palettes(root / "palettes.bin")
    if pieces is None:
        pieces = [p for group in build_roster().values() for p in group]
    rigs, result = rig_catalog(), {}
    for piece in sorted(pieces, key=lambda p: p.species_id):
        sid = piece.species_id
        profile, skill, move = profile_of(sid), skill_of(sid), resolve_cast(piece)
        signature = bool(skill and skill["tier"] == "signature")
        rig = rigs.get(str(sid), {"implemented": False, "parts": [], "anchors": {}})
        if sid in species_motion:
            validate_motion(sid)
        elif rig['implemented']:
            raise ValueError(f'rig/{sid}: 部件动作需要先提供完整整身动画表')
        errors = []
        blob = front.blob_of.get(sid)
        if blob is None:
            errors.append(f"缺少精灵资源 front/{sid}")
        elif len(blob) != front.size_of.get(sid, 0) ** 2 // 4:
            errors.append(f"精灵资源 front/{sid} 数据长度错误")
        elif not blob or all(b == 255 for b in blob):
            errors.append(f"精灵资源 front/{sid} 全透明")
        try:
            palettes.for_species(sid)
        except (ValueError, IndexError, KeyError) as exc:
            errors.append(f"缺少有效色板 species/{sid}: {exc}")
        arch = skill["arch"] if skill else None
        description, tactic, counterplay = GENERIC_TACTICS.get(arch, ("使用学习表中的伤害招式", "依照属性与射程安排站位", "用属性克制与站位应对。"))
        description = GENERIC_DESCRIPTIONS.get(arch, description)
        attack, cast = "程序化蓄力、出手、回收", "通用技能模板，按真实命中播放"
        if signature:
            description = profile["ult"].get("note", GENERIC_DESCRIPTIONS.get(arch, skill["name"]))
            if sid in TACTICS:
                tactic, counterplay, attack, cast = TACTICS[sid]
        elif sid in species_motion:
            attack = "手编整身动作与真实命中时序"
        if not move:
            description, cast = "当前规则下无可施放技能", "不支持施法"
        authored = AUTHORED_SKILLS.get(sid)
        authored_vfx = bool(move and authored and authored[0] == move["id"])
        body = "part_rig" if rig["implemented"] else "authored_pose" if sid in species_motion else "procedural"
        effect = ("none" if not move else "layered" if sid in SUPPORTED_SPECIES
                  else "authored" if authored_vfx else "archetype")
        controls = ["palette", "effect_scale", "particle_density", "motion_scale"] if sid in SUPPORTED_SPECIES else []
        result[str(sid)] = {
            **mode_info(mode),
            "species": sid, "name": piece.name,
            "role": profile.get("role", "通用技能") if profile else "通用技能",
            "cost": piece.tier, "range": effective_range(piece),
            "skill": {"move_id": piece.move_id, "name": (move.get("name_zh") or move["name"]) if move else "无",
                      "tier": skill["tier"] if skill and move else "legacy" if move else "none",
                      "arch": arch, "can_cast": bool(move), "fallback_payload": bool(move and piece.move_id is None),
                      "description": description, "tactic": tactic, "counterplay": counterplay},
            "rig": rig, "motion_notes": {"attack": attack, "cast": cast},
            "capabilities": {"body": body, "effect": effect, "resource_ready": not errors,
                             "resource_errors": errors,
                             "actions": [kind for kind in PREVIEW_ACTIONS if kind != 'cast' or move],
                             "action_matrix": action_coverage(sid, rig, sid in species_motion, bool(move)),
                             "editable_controls": controls},
        }
    return result


def _arena_catalog(*, pieces=None, asset_root=None):
    """The trial's actual 48 templates, native skills and independently shipped art."""
    from pathlib import Path
    import copy
    import arena
    import arena_skills
    import web_motion
    import retro_native
    from action_preview import action_coverage, PREVIEW_ACTIONS
    from decoders import Front, Palettes
    from motion import species_motion, validate_motion
    from presentation_modes import mode_info
    from profiles import effective_range

    if asset_root is None:
        front, palettes = Front(), Palettes()
    else:
        root = Path(asset_root)
        front, palettes = Front(root / 'gen1_front.bin'), Palettes(root / 'palettes.bin')
        front._allow_local_png, front._png_root = True, root / 'gen2'
    pieces = list(arena.build_templates().values()) if pieces is None else pieces
    rigs, result = rig_catalog(), {}
    controls = ['palette', 'effect_scale', 'particle_density', 'motion_scale']
    notes = {68: ('四条肩肘轨道交替出拳', '四臂蓄力、交错追击与收招'),
             26: ('耳朵摆动，尾巴独立蓄电', '脸颊释放电流，耳尾跟随充能'),
             212: ('双钳分别出击，翅膀独立摆动', '交叉弹拳与双钳收招')}
    for piece in sorted(pieces, key=lambda p: p.species_id):
        sid = piece.species_id
        if sid not in arena.ROSTER:
            raise ValueError(f'精灵 {sid} 不在竞技试玩池中')
        skill, move = arena_skills.skill_of(sid), arena_skills.resolve_cast(piece)
        rig = copy.deepcopy(rigs.get(str(sid), {'implemented': False, 'parts': [], 'anchors': {}}))
        authored = sid in species_motion
        if authored:
            validate_motion(sid)
        web_parts = web_motion.supports(sid)
        if web_parts:
            reference, limbs = web_motion.RIGS[sid]
            labels = {'fist_0': '后臂一', 'fist_1': '前臂一', 'fist_2': '后臂二', 'fist_3': '前臂二',
                      'claw_0': '左钳', 'claw_1': '右钳', 'wing_0': '左翼', 'wing_1': '右翼',
                      'tail': '尾巴', 'ear_0': '左耳', 'ear_1': '右耳'}
            rig = {'implemented': True, 'format': 'web_polygon_joints', 'source': 'web_motion',
                   'parts': [{'name': 'body', 'label': '躯干与脚底', 'pivot_percent': [50, 100]}] +
                            [{'name': limb.name, 'label': labels[limb.name],
                              'pivot_percent': [round(limb.root[0]/reference[0]*100, 2),
                                                round(limb.root[1]/reference[1]*100, 2)]}
                             for limb in limbs],
                   'anchors': {limb.name: {'part': limb.name,
                                          'point_percent': [round(limb.tip[0]/reference[0]*100, 2),
                                                            round(limb.tip[1]/reference[1]*100, 2)]}
                               for limb in limbs},
                   'actions': {'attack': {'parts': [limb.name for limb in limbs]},
                               'cast': {'parts': [limb.name for limb in limbs]}},
                   'limits': {'parts': len(limbs)+1},
                   'note': '网页多边形部件与独立关节；整身位置和受击仍由共享回放计算'}
        errors = []
        for shiny in (False, True):
            try:
                front.image(sid, palettes, shiny=shiny)
                front.palette_for_species(sid, palettes, shiny=shiny)
            except (ValueError, OSError, IndexError, KeyError) as exc:
                errors.append(f'{"闪光" if shiny else "普通"}精灵资源 species/{sid}: {exc}')
        local_png = front._uses_local_png(sid)
        resources = ({'source': 'gen2_png',
                      'normal': str(front._png_root / 'normal' / f'{sid}.png'),
                      'shiny': str(front._png_root / 'shiny' / f'{sid}.png')}
                     if local_png else {'source': 'gen1_front', 'normal': str(front.path),
                                        'shiny': str(front.path), 'palettes': str(palettes.path)})
        matrix = action_coverage(sid, rig, authored, True)
        if web_parts:
            for action in ('idle', 'move'):
                matrix[action]['parts'] = 'procedural_joints'
            matrix['status']['note'] = '共享冻结定格和状态标识；网页部件轨道也按首次冻结时刻采样'
        body = 'web_part_rig' if web_parts else 'part_rig' if rig['implemented'] else 'authored_pose' if authored else 'procedural'
        attack, cast = notes.get(sid, ('共享整身动作与真实命中时序' if authored else '程序化蓄力、出手、回收',
                                       '原生技能按蓄力、飞行、命中、余波呈现'))
        role = getattr(piece, 'role_key', None) or arena.ROSTER[sid][1]
        result[str(sid)] = {**mode_info('arena'), 'species': sid, 'name': piece.name,
            'role': arena.ROLE_NAMES[role], 'role_key': role,
            'cost': piece.tier, 'range': effective_range(piece), 'types': list(piece.types),
            'skill': {'move_id': move['name'], 'native_id': skill['id'], 'name': skill['name'],
                      'type': skill['type'], 'tier': 'native', 'arch': skill['id'], 'can_cast': True,
                      'fallback_payload': False, 'description': skill['description'],
                      'presentation': retro_native.describe(skill['id']),
                      'tags': list(skill['tags']), 'tactic': '、'.join(skill['tags']),
                      'counterplay': '结合属性克制、目标距离和站位，避免敌方技能连续触发。'},
            'resources': resources, 'rig': rig, 'motion_notes': {'attack': attack, 'cast': cast},
            'capabilities': {'body': body, 'whole_body': 'authored_pose' if authored else 'procedural',
                             'parts': 'web_polygon_joints' if web_parts else 'source_slice_rig' if rig['implemented'] else 'none',
                             'effect': 'arena_native', 'resource_ready': not errors,
                             'resource_errors': errors, 'actions': list(PREVIEW_ACTIONS),
                             'action_matrix': matrix, 'editable_controls': list(controls)}}
    return result
