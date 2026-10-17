"""Authored presentation for family forms outside the two frozen VFX packs.

The module is intentionally a leaf: renderers may import it, but it never
imports ``arena_vfx`` (or the dispatch that calls it).  Every entry names a
real species and describes both its basic attack and the native kit selected
by ``arena_skills``.  Drawing is finite and deterministic: source, target and
emitter coordinates are replay facts, never target selection.
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw

import retro_primitives as rp

# Keep this list explicit.  Integration derives the same set from
# families_v2 minus arena_vfx.EFFECTS minus the Hoenn pack; this module owns no
# simulation dependency and cannot accidentally admit a combat-only species.
_DESIGNS = {
    1: ('种子叶击', '初阶·日光反哺', '背种光源放射三叶日光', 'back bulb', 1,
        'GRASS', 'seed_leaf', 'solar_seed'),
    2: ('花苞叶刃', '初阶·日光反哺', '花苞光源外扩成环形叶光', 'back bud', 2,
        'GRASS', 'seed_leaf', 'solar_seed'),
    4: ('尾焰轻吐', '火花', '尾焰光源牵出口前小火锥', 'tail flame', 1,
        'FIRE', 'tail_flame', 'tail_ember'),
    5: ('焰爪前推', '火花', '口前火焰压缩成爪形火路', 'mouth flame', 2,
        'FIRE', 'tail_flame', 'tail_ember'),
    7: ('壳旋水沫', '水枪', '口部螺旋水柱带壳旋导流', 'mouth jet', 1,
        'WATER', 'shell_jet', 'shell_jet'),
    8: ('双涡水箭', '水枪', '口部主水箭与壳缘导流合成双涡', 'mouth jet', 2,
        'WATER', 'shell_jet', 'shell_jet'),
    10: ('丝线缠绊', '初阶·净化蝶粉', '吐丝结成透亮茧光', 'mouth silk', 1,
        'BUG', 'silk', 'silk_cocoon'),
    11: ('硬壳顶击', '初阶·净化蝶粉', '茧壳裂缝中放出净化粉', 'shell seam', 2,
        'BUG', 'silk', 'silk_cocoon'),
    25: ('颊囊电弹', '电击', '双颊电囊先缩后放出折线电流', 'cheek pouches', 2,
        'ELECTRIC', 'cheek_bolt', 'cheek_bolt'),
    29: ('月牙毒针', '毒针', '护身月牙带出毒针', 'back horn', 1,
        'POISON', 'needle_fan', 'venom_crescent'),
    30: ('双月甲刺', '毒针', '双月甲片夹成毒环', 'back plates', 2,
        'POISON', 'needle_fan', 'venom_crescent'),
    32: ('独角钻刺', '毒针', '独角螺旋前进并甩出毒屑', 'forehead horn', 1,
        'POISON', 'horn_drill', 'venom_drill'),
    33: ('裂角毒钻', '毒针', '裂角展开成三段钻刃', 'forehead horns', 2,
        'POISON', 'horn_drill', 'venom_drill'),
    35: ('星尘轻拍', '初阶·月光祝福', '月尘从翼尖汇成护盾', 'wing tips', 2,
        'NORMAL', 'moon_dust', 'moon_shell'),
    39: ('歌声涟漪', '初阶·治愈歌声', '歌声以心形波展开治疗', 'mouth song', 2,
        'NORMAL', 'song_note', 'song_wave'),
    43: ('根须夜露球', '初阶·芳香花域', '双脚根须引出露珠雾幕', 'root feet', 1,
        'GRASS', 'aroma_bud', 'aroma_bloom'),
    44: ('腐香花幕', '初阶·芳香花域', '花蜜下压成净化雾幕', 'flower center', 2,
        'GRASS', 'aroma_bud', 'aroma_bloom'),
    58: ('斑纹火冲', '火花', '背纹发热后向前扑火', 'back stripes', 1,
        'FIRE', 'ember_dash', 'ember_dash'),
    63: ('瞬移念泡', '念力', '短距折跃留下的念泡与折线残影', 'psychic focus', 1,
        'PSYCHIC', 'warp_orb', 'warp_spoon'),
    64: ('单勺引导', '念力', '单勺划出稳定的念链', 'one spoon', 2,
        'PSYCHIC', 'warp_orb', 'warp_spoon'),
    66: ('低架冲拳', '碎岩', '低位拳路推出碎石冲线', 'right fist', 1,
        'FIGHTING', 'training_fist', 'training_fist'),
    67: ('腰带重拳', '碎岩', '腰带光带与交叉拳路合成轰击', 'power belt', 2,
        'FIGHTING', 'training_fist', 'training_fist'),
    72: ('触珠水泡', '水枪', '头顶红珠与触手同步放泡', 'cranial orb', 1,
        'WATER', 'jelly_bead', 'jelly_pulse'),
    74: ('拳石飞转', '落石', '双臂收拢后石身旋转掷出', 'both fists', 1,
        'ROCK', 'boulder_roll', 'boulder_roll'),
    75: ('四臂石轮', '落石', '四臂展开成碎石轮', 'four arms', 2,
        'ROCK', 'boulder_roll', 'boulder_roll'),
    79: ('尾尖水圈', '水枪', '尾尖点水形成迟缓波圈', 'tail tip', 1,
        'WATER', 'tail_ripple', 'tail_ripple'),
    90: ('壳舌夹击', '水枪', '壳舌夹紧时喷出冷水', 'shell tongue', 1,
        'WATER', 'clamp_frost', 'clamp_frost'),
    92: ('瓦斯鬼火', '惊吓', '瓦斯团裂开露出幽火', 'gas body', 1,
        'GHOST', 'gas_orb', 'gas_lantern'),
    116: ('细嘴水线', '水枪', '细嘴高压水线左右摆动', 'narrow snout', 1,
        'WATER', 'water_spiral', 'dragon_current'),
    117: ('刺鳍涡流', '水枪', '背鳍卷出成对涡流', 'dorsal fins', 2,
        'WATER', 'water_spiral', 'dragon_current'),
    120: ('核心星芒', '初阶·星光共鸣', '核心红光向友方送出星芒', 'central core', 1,
        'WATER', 'core_star', 'star_relay'),
    129: ('扑水跃击', '奋力跃击', '弱小但完整的弧形扑水', 'whole body', 1,
        'NORMAL', 'splash_arc', 'splash_arc'),
    130: ('怒涛颚击', '怒涛冲撞', '怒涛沿龙身收拢成巨颚', 'open maw', 2,
        'WATER', 'torrent_maw', 'torrent_maw'),
    133: ('多向撞光', '撞击', '颈环放射八向光痕', 'neck ruff', 1,
        'NORMAL', 'adaptive_ring', 'adaptive_ring'),
    134: ('水尾波枪', '水流护幕', '尾鳍展开成环护住自身', 'tail fin', 2,
        'WATER', 'water_veil', 'water_veil'),
    135: ('雷针连锁', '雷电接力', '针毛接成三角雷路', 'needle mane', 2,
        'ELECTRIC', 'chain_arrow', 'chain_arrow'),
    136: ('炽鬃迸发', '烈焰迸发', '炽鬃光环向外轰开', 'fire mane', 2,
        'FIRE', 'flame_burst', 'flame_crown'),
    147: ('细身龙波', '属性冲击', '细身摆动牵出龙环', 'white nose', 1,
        'DRAGON', 'dragon_serpent', 'dragon_current'),
    152: ('叶领轻扫', '初阶·清露花幕', '叶领露水结成花幕', 'leaf collar', 1,
        'GRASS', 'collar_leaf', 'leaf_collar'),
    153: ('芽苞露环', '初阶·清露花幕', '头顶叶片与颈芽光环扩成露环', 'head leaf', 2,
        'GRASS', 'collar_leaf', 'leaf_collar'),
    155: ('背焰小锥', '火花', '背上四个火孔斜向喷焰', 'back vents', 1,
        'FIRE', 'vent_flame', 'vent_flare'),
    156: ('环焰喷射', '火花', '头背与臀部火焰连成喷射带', 'back vents', 2,
        'FIRE', 'vent_flame', 'vent_flare'),
    158: ('稚颚水咬', '水枪', '稚颚咬合带出水花', 'young jaws', 1,
        'WATER', 'jaw_water', 'jaw_rush'),
    159: ('花纹水颚', '水枪', '花纹颚部张开夹住水流', 'patterned jaws', 2,
        'WATER', 'jaw_water', 'jaw_rush'),
    161: ('尾座弹击', '撞击', '尾座光环向前弹射冲线', 'tail stand', 1,
        'NORMAL', 'tail_spring', 'tail_spring'),
    163: ('夜目翼波', '初阶·守夜安抚', '夜目与翼羽同步发出安抚波', 'night-eye discs', 1,
        'FLYING', 'lunar_wing', 'lullaby_orbit'),
    170: ('双灯电流', '初阶·灯塔接力', '双灯向下导出电流接力', 'two antennae', 1,
        'ELECTRIC', 'twin_lantern', 'twin_beacon'),
    172: ('颊电小爆', '电击', '幼小颊电失控小爆', 'baby cheeks', 1,
        'ELECTRIC', 'cheek_bolt', 'pichu_spark'),
    173: ('小星护拍', '初阶·月光祝福', '小星连成摇篮护罩', 'star points', 1,
        'NORMAL', 'moon_dust', 'star_nursery'),
    174: ('摇篮声波', '初阶·治愈歌声', '声波在额前形成摇篮光', 'forehead knot', 1,
        'NORMAL', 'song_note', 'song_wave'),
    179: ('绒毛静电', '电击', '绒毛光球压成静电前路', 'wool fleece', 1,
        'ELECTRIC', 'wool_charge', 'wool_charge'),
    180: ('粉红电涡', '电击', '粉色绒毛卷成双涡', 'pink fleece', 2,
        'ELECTRIC', 'wool_charge', 'wool_charge'),
    194: ('泥水扇面', '水枪', '外鳃与尾侧水痕合成泥水扇', 'external gills', 1,
        'WATER', 'mud_fan', 'mud_pad'),
    236: ('立姿突拳', '碎岩', '立姿摆拳并留下白色拳路', 'leading fist', 1,
        'FIGHTING', 'training_fist', 'training_fist'),
    238: ('亲吻冰晶', '细雪', '唇温凝成小冰晶', 'kiss point', 1,
        'ICE', 'frost_kiss', 'frost_kiss'),
    239: ('插头电弧', '电击', '头部插脚放出双头电弧', 'plug prongs', 1,
        'ELECTRIC', 'plug_arc', 'plug_arc'),
    246: ('岩壳小突', '落石', '岩壳前端顶出碎屑', 'head shell', 1,
        'ROCK', 'boulder_roll', 'boulder_roll'),
    247: ('茧岩破口', '落石', '茧岩破口喷出砂柱', 'shell opening', 2,
        'ROCK', 'boulder_roll', 'boulder_roll'),
}

SPECIES = frozenset(_DESIGNS)
_FIELDS = ('attack_name', 'cast_name', 'identity', 'emitter', 'stage',
           'element', 'motif', 'cast_kind')
_MOTIF_ALIASES = {
    '根须夜露球': 'aroma_bud',
}


def _entry(sid):
    return dict(zip(_FIELDS, _DESIGNS[sid]))


def attack_label(sid):
    """Return the short label used by the old attack catalog and previews."""
    return _DESIGNS[sid][0] if sid in SPECIES else None


def describe(sid):
    """Presentation metadata only; battle data stays in ``arena_skills``."""
    if sid not in SPECIES:
        return None
    entry = _entry(sid)
    return {
        'attack_name': entry['attack_name'],
        'cast_name': entry['cast_name'],
        'identity': entry['identity'],
        'emitter': entry['emitter'],
        'stage': entry['stage'],
        'element': entry['element'],
        'motif': entry['motif'],
        'cast_kind': entry['cast_kind'],
    }


def _snap(value):
    return int(round(value / rp.PIXEL) * rp.PIXEL)


def _pt(point):
    return _snap(point[0]), _snap(point[1])


def _polygon(d, points, color, width=0, outline=None):
    pts = [(_snap(x), _snap(y)) for x, y in points]
    if width <= 0:
        d.polygon(pts, fill=color, outline=outline)
    else:
        d.line(pts, fill=color, width=max(1, round(width / rp.PIXEL)), joint='curve')


def _line(d, points, color, width=3):
    _polygon(d, points, color, width)


def _circle(d, center, radius, color, *, width=0, outline=None):
    x, y = center
    r = max(rp.PIXEL, _snap(radius))
    box = (x-r, y-r, x+r, y+r)
    if width:
        d.ellipse(box, outline=color, width=max(1, round(width / rp.PIXEL)))
    else:
        d.ellipse(box, fill=color, outline=outline)


def _small_star(d, x, y, radius, color, points=5, angle=-math.pi/2):
    pts = []
    for i in range(points * 2):
        rr = radius if i % 2 == 0 else radius * .42
        pts.append((x + math.cos(angle + i*math.pi/points)*rr,
                    y + math.sin(angle + i*math.pi/points)*rr))
    d.polygon(pts, fill=color)


def _ink(element):
    return rp.palette(element, {})


def draw_attack_motif(d, sid, x, y, k, angle, hit):
    """Draw the compact 64x64 motif expected by the legacy attack renderer."""
    if sid not in SPECIES:
        return False
    e = _entry(sid)
    motif = _MOTIF_ALIASES.get(e['motif'], e['motif'])
    c = _ink(e['element'])
    stage = e['stage']
    r = 7 + max(0., min(1., float(k))) * (7 + stage * 2)
    turn = angle + k * 2.4

    if motif == 'seed_leaf':
        _circle(d, (x, y+3), 5+stage, c[2], outline=c[3])
        for i in range(2 + stage):
            a = angle + (i-(1+stage)/2)*.45
            _polygon(d, ((x, y+2), (x+math.cos(a)*r, y+2+math.sin(a)*r),
                         (x+math.cos(a+.42)*(r-3), y+2+math.sin(a+.42)*(r-3))), c[3])
    elif motif == 'tail_flame':
        pts = ((x-r, y+4), (x-r*.4, y-r*.5), (x+r*.2, y), (x+r, y-r*.8), (x+r*.65, y+4))
        _polygon(d, pts, c[2], outline=c[3])
        _line(d, ((x-r*.7, y+2), (x, y-1), (x+r*.5, y+2)), c[4], 2)
    elif motif == 'shell_jet':
        for lane in range(stage):
            yy = y + (lane-(stage-1)/2)*6
            _line(d, ((x-r, yy+3), (x-r*.2, yy), (x+r, yy-3)), c[2], 5-stage)
        _circle(d, (x+r, y), 3+stage, c[3], width=2)
    elif motif == 'silk':
        route = [(x-r+i*3, y+math.sin(i*.75+turn)*6) for i in range(9)]
        _line(d, route, c[3], 3)
        for q in (.2, .55, .85):
            _circle(d, (x-r+q*2*r, y+math.sin(q*6+turn)*6), 2+stage, c[4])
    elif motif == 'cheek_bolt':
        for side in (-1, 1):
            xx = x + side*(5+stage)
            _line(d, ((xx-r*.5, y-5), (xx-2, y), (xx+3, y-3), (xx-r*.4, y+6)), c[3], 3)
        _line(d, ((x-r, y), (x+r, y)), c[4], 2)
    elif motif == 'needle_fan':
        for i in range(3+stage):
            a = turn + (i-(2+stage)/2)*.36
            _line(d, ((x-math.cos(a)*r*.3, y+4-math.sin(a)*r*.3),
                      (x+math.cos(a)*r, y+4-math.sin(a)*r)), c[3], 2)
        _circle(d, (x, y+4), 3, c[2])
    elif motif == 'horn_drill':
        turns = 2 + stage
        for i in range(turns):
            rr = r * (i+1)/turns
            d.arc((x-rr, y-rr*.55, x+rr, y+rr*.55), 200+turn*40, 350+turn*40, fill=c[2], width=2)
        _polygon(d, ((x-r, y+4), (x+r, y), (x-r, y-4)), c[3], outline=c[4])
    elif motif == 'moon_dust':
        _small_star(d, x, y, r*.8, c[3], 5+stage)
        for i in range(3+stage*2):
            a = turn + i*math.tau/(3+stage*2)
            _circle(d, (x+math.cos(a)*r, y+math.sin(a)*r*.7), 2, c[4])
    elif motif == 'song_note':
        _circle(d, (x-3, y+3), 4+stage, c[3])
        _line(d, ((x+1+stage, y+3), (x+1+stage, y-8-stage), (x+7+stage, y-4)), c[4], 2)
        if hit:
            d.arc((x-r, y-r*.65, x+r, y+r*.65), 190, 350, fill=c[3], width=1)
    elif motif == 'aroma_bud':
        petals = 4+stage
        for i in range(petals):
            a = turn+i*math.tau/petals
            _circle(d, (x+math.cos(a)*5, y+math.sin(a)*4), 3, c[2])
        _circle(d, (x, y), 3+stage*.5, c[4])
    elif motif == 'ember_dash':
        for i in range(stage+2):
            yy = y + (i-(stage+1)/2)*5
            _line(d, ((x-r, yy+3), (x+r*.6, yy-2), (x+r, yy)), c[2 if i%2 else 3], 2+stage)
    elif motif == 'warp_orb':
        for i in range(2+stage):
            rr = r*(.45+i*.28)
            d.ellipse((x-rr, y-rr*.65, x+rr, y+rr*.65), outline=c[3], width=2)
        _circle(d, (x, y), 3+stage, c[4])
    elif motif == 'training_fist':
        _polygon(d, ((x-r*.6, y+r*.35), (x-r*.25, y-r*.45), (x+r*.7, y-r*.2),
                     (x+r*.55, y+r*.45)), c[3], outline=c[4])
        for i in range(stage+1):
            _line(d, ((x-r*.8, y+i*3-2), (x+r*.8, y+i*3-4)), c[2], 2)
    elif motif == 'jelly_bead':
        for i in range(stage+1):
            _circle(d, (x-r+i*r*2/(stage or 1), y+4), 3, c[2], outline=c[3])
        _line(d, ((x-r, y-3), (x, y-8-turn%2*2), (x+r, y-3)), c[3], 2)
    elif motif == 'boulder_roll':
        pts = [(x+math.cos(i*math.tau/(5+stage)+turn)*r,
                y+math.sin(i*math.tau/(5+stage)+turn)*r*.82)
               for i in range(5+stage)]
        _polygon(d, pts, c[2], outline=c[3])
        _line(d, ((pts[0], (x, y), pts[2])), c[1], 2)
    elif motif == 'tail_ripple':
        for i in range(stage+2):
            rr = r*(.42+i*.25)
            d.arc((x-rr, y-rr*.55, x+rr, y+rr*.55), 180, 350, fill=c[2+i%2], width=2)
    elif motif == 'clamp_frost':
        for side in (-1, 1):
            d.arc((x+side*r*.3-r*.7, y-r*.7, x+side*r*.3+r*.7, y+r*.7),
                  250 if side < 0 else 70, 80 if side < 0 else 200, fill=c[2], width=3)
        for i in range(stage+1):
            _circle(d, (x, y+(i-(stage/2))*5), 2, c[4])
    elif motif == 'gas_orb':
        _circle(d, (x, y), r*.75, c[1] + (160,), outline=c[3])
        _small_star(d, x-r*.3, y-r*.2, r*.28, c[4], 4, turn)
        _small_star(d, x+r*.35, y+r*.15, r*.22, c[3], 4, -turn)
    elif motif == 'water_spiral':
        for arm in range(1+stage):
            route = [(x+math.cos(i*.7+turn+arm*2.1)*(2+i*r/8),
                      y+math.sin(i*.7+turn+arm*2.1)*(2+i*r/10)) for i in range(8)]
            _line(d, route, c[2+arm%2], 2)
    elif motif == 'core_star':
        _small_star(d, x, y, r, c[3], 5+stage*2, turn)
        _circle(d, (x, y), 3+stage, c[2])
    elif motif == 'splash_arc':
        _line(d, ((x-r, y+4), (x, y-r), (x+r, y+4)), c[3], 3)
        for side in (-1, 1):
            _circle(d, (x+side*r*.55, y+4), 2, c[4])
    elif motif == 'torrent_maw':
        _polygon(d, ((x-r, y-r*.25), (x+r*.2, y-r*.65), (x+r, y), (x+r*.2, y+r*.65), (x-r, y+r*.25)), c[2], outline=c[3])
        for i in range(stage+3):
            _line(d, ((x-r*.7+i*r*.35, y-r*.3), (x-r*.5+i*r*.35, y+r*.3)), c[4], 2)
    elif motif == 'adaptive_ring':
        directions = 4+stage*2
        for i in range(directions):
            a = turn+i*math.tau/directions
            _line(d, ((x+math.cos(a)*4, y+math.sin(a)*4),
                      (x+math.cos(a)*r, y+math.sin(a)*r*.8)), c[3], 2)
        _circle(d, (x, y), 4, c[4])
    elif motif == 'water_veil':
        for i in range(stage+1):
            _circle(d, (x, y), r*(.45+i*.25), c[2], width=2, outline=c[3])
        _line(d, ((x-r*.5, y), (x, y-r*.5), (x+r*.5, y)), c[4], 2)
    elif motif == 'chain_arrow':
        route = [(x-r+i*r/4, y+(0 if i in (0, 4) else (-6 if i % 2 else 6))) for i in range(5)]
        _line(d, route, c[3], 3)
        _small_star(d, x+r, y, 4, c[4], 4, angle)
    elif motif == 'flame_burst':
        for i in range(stage+3):
            a = turn+i*math.tau/(stage+3)
            _line(d, ((x, y), (x+math.cos(a)*r, y+math.sin(a)*r*.75)), c[2 if i%2 else 3], 2)
        _circle(d, (x, y), 4, c[4])
    elif motif == 'dragon_serpent':
        route = [(x-r+i*r/7, y+math.sin(i*.8+turn)*(4+stage)) for i in range(8)]
        _line(d, route, c[3], 3)
        _circle(d, (x+r, y+math.sin(6.4+turn)*(4+stage)), 3, c[4])
    elif motif == 'collar_leaf':
        for i in range(stage+2):
            a = turn+i*math.tau/(stage+2)
            _polygon(d, ((x, y), (x+math.cos(a)*r, y+math.sin(a)*r*.7),
                         (x+math.cos(a+.5)*(r-3), y+math.sin(a+.5)*(r-3))), c[3])
        _circle(d, (x, y), 3, c[4])
    elif motif == 'vent_flame':
        for i in range(stage+3):
            xx = x-r+(i%(stage+3))*r*2/max(1, stage+2)
            yy = y + (3 if i % 2 else -2)
            _polygon(d, ((xx, yy+3), (xx+2, yy-5-stage), (xx+5, yy+3)), c[2 if i%2 else 3])
    elif motif == 'jaw_water':
        for side in (-1, 1):
            _line(d, ((x-r*.5, y+side*4), (x+r*.45, y+side*7), (x+r, y+side*2)), c[3], 2+stage)
        _polygon(d, ((x-r*.35, y), (x+r*.35, y-4), (x+r*.35, y+4)), c[4])
    elif motif == 'tail_spring':
        for i in range(stage+3):
            d.arc((x-r+i*r/(stage+3), y-4, x-r+(i+1)*r/(stage+3), y+4), 180 if i%2 else 0,
                  360 if i%2 else 180, fill=c[3], width=2)
        _circle(d, (x+r, y), 3, c[4])
    elif motif == 'lunar_wing':
        for side in (-1, 1):
            d.arc((x+side*r*.3-r*.7, y-r*.45, x+side*r*.3+r*.7, y+r*.45),
                  250 if side < 0 else 70, 20 if side < 0 else 200, fill=c[3], width=2)
        _circle(d, (x, y), 3+stage, c[4])
    elif motif == 'twin_lantern':
        for side in (-1, 1):
            _circle(d, (x+side*r*.45, y), 4, c[3], outline=c[4])
            _line(d, ((x+side*r*.45, y+4), (x+side*r*.2, y+r*.6)), c[2], 2)
    elif motif == 'moon_dust':
        # Aliased by aroma and older entries above; retained for direct callers.
        _small_star(d, x, y, r*.8, c[3], 5+stage)
    elif motif == 'wool_charge':
        for i in range(stage+3):
            a = turn+i*math.tau/(stage+3)
            _circle(d, (x+math.cos(a)*r*.55, y+math.sin(a)*r*.45), 3, c[3])
        _line(d, ((x-r*.5, y), (x+r*.5, y)), c[4], 2)
    elif motif == 'mud_fan':
        for i in range(stage+3):
            a = -.45+(i/(stage+2))*.9
            _line(d, ((x, y+3), (x+math.cos(a)*r, y+3+math.sin(a)*r*.5)), c[2 if i%2 else 3], 2)
        _circle(d, (x, y+3), 3, c[4])
    elif motif == 'frost_kiss':
        for i in range(6):
            a = turn+i*math.tau/6
            _line(d, ((x, y), (x+math.cos(a)*r*.75, y+math.sin(a)*r*.75)), c[3], 2)
        for i in range(6):
            a = turn+i*math.tau/6
            _circle(d, (x+math.cos(a)*r*.75, y+math.sin(a)*r*.75), 2, c[4])
    elif motif == 'plug_arc':
        for side in (-1, 1):
            xx = x+side*5
            _line(d, ((xx, y-r), (xx-3, y), (xx+4, y-2), (xx, y+r)), c[3], 3)
        _line(d, ((x-r, y), (x+r, y)), c[4], 2)
    else:  # defensive, but every registered motif has an authored branch
        _small_star(d, x, y, r, c[3], 5, angle)
    if hit:
        for i in range(4+stage):
            a = angle+i*math.tau/(4+stage)
            _line(d, ((x+math.cos(a)*r*.8, y+math.sin(a)*r*.65),
                      (x+math.cos(a)*(r+5), y+math.sin(a)*(r+4))), c[4], 2)
    return True

def _vivid(cel):
    if cel.mode != 'RGBA':
        return cel.convert('RGBA')
    r, g, b, alpha = cel.split()
    lut = [max(0, min(255, round((v-128)*1.22+136))) for v in range(256)]
    from PIL import Image
    return Image.merge('RGBA', (r.point(lut), g.point(lut), b.point(lut), alpha))


def _sprite(layer, sid, at, size, k, angle, config, *, alpha=1.):
    from PIL import Image
    cel = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    if not draw_attack_motif(ImageDraw.Draw(cel), sid, 32, 32, k, angle, k > .45):
        return
    if config.get('palette') == 'vivid':
        cel = _vivid(cel)
    if alpha < 1:
        cel = cel.copy()
        cel.putalpha(cel.getchannel('A').point(lambda a: round(a*alpha)))
    # Size is a screen-space target; snap its side to the three-pixel grid.
    side = max(rp.PIXEL, _snap(size))
    cel = cel.resize((side, side), Image.Resampling.NEAREST)
    layer.alpha_composite(cel, (_snap(at[0]-side/2), _snap(at[1]-side/2)))


def _between(a, b, q):
    return a[0]+(b[0]-a[0])*q, a[1]+(b[1]-a[1])*q


def _normal(a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy) or 1.
    return -dy/length, dx/length


def _travel_point(a, b, q, kind, stage):
    x, y = _between(a, b, q)
    nx, ny = _normal(a, b)
    if kind in ('tail_ember', 'tail_spring', 'jaw_rush'):
        lift = -math.sin(q*math.pi)*(14+stage*4)
        return x+nx*lift*.2, y+ny*lift*.2-lift
    if kind in ('shell_jet', 'dragon_current', 'water_veil'):
        wave = math.sin(q*math.tau*(1.2+stage*.2))*(8+stage*3)
        return x+nx*wave, y+ny*wave
    if kind in ('cheek_bolt', 'pichu_spark', 'chain_arrow', 'plug_arc', 'twin_beacon'):
        wave = math.sin(q*math.tau*2.5)*(10+stage*3)
        return x+nx*wave, y+ny*wave
    if kind in ('solar_seed', 'leaf_collar', 'aroma_bloom'):
        wave = math.sin(q*math.pi)*(12+stage*4)
        return x+nx*wave, y+ny*wave
    if kind == 'splash_arc':
        return x, y-math.sin(q*math.pi)*(42+stage*7)
    if kind == 'warp_spoon':
        wave = math.sin(q*math.tau*2)*(16+stage*4)
        return x+nx*wave, y+ny*wave
    return x, y


def _cast_route(a, b, p, kind, stage):
    start = max(0., p-.34)
    return [_travel_point(a, b, q, kind, stage) for q in
            (start+(i/12)*(p-start) for i in range(13))]


def _charge(layer, d, sid, origin, p, config):
    e = _entry(sid)
    c = rp.palette(e['element'], config)
    scale, density = rp.settings(config)
    stage = e['stage']
    radius = (19+stage*7+p*16)*scale
    kind = e['cast_kind']
    x, y = origin
    if kind in ('solar_seed', 'leaf_collar', 'aroma_bloom'):
        leaves = 3+stage*2
        for i in range(round(leaves*density)):
            a = -math.pi/2 + (i-(leaves-1)/2)*.42
            _line(d, ((x, y+8), (x+math.cos(a)*radius, y+8+math.sin(a)*radius*.55)), c[3], 4)
        _circle(d, (x, y+10), 4+stage+p*5, c[4], outline=c[3])
    elif kind in ('tail_ember', 'ember_dash', 'vent_flare', 'flame_crown'):
        for i in range(round((3+stage)*density)):
            a = math.pi*.65+i*math.tau/(3+stage)
            _line(d, ((x+math.cos(a)*5, y+math.sin(a)*5),
                      (x+math.cos(a)*radius, y+math.sin(a)*radius*.75)), c[2 if i%2 else 3], 4)
    elif kind in ('shell_jet', 'dragon_current', 'water_veil', 'jaw_rush', 'tail_ripple', 'mud_pad'):
        for i in range(round((3+stage)*density)):
            rr = radius*(.42+i*.19)
            d.arc((x-rr, y-rr*.62, x+rr, y+rr*.62), 175, 355, fill=c[2+i%2], width=3)
    elif kind in ('cheek_bolt', 'pichu_spark', 'chain_arrow', 'plug_arc', 'twin_beacon', 'wool_charge'):
        points = 3+stage*2
        for i in range(round(points*density)):
            a = p*math.tau+i*math.tau/points
            _circle(d, (x+math.cos(a)*radius*.55, y+math.sin(a)*radius*.45), 3, c[3 if i%2 else 4])
        _line(d, ((x-radius*.4, y), (x+radius*.4, y)), c[3], 3)
    elif kind in ('moon_shell', 'star_nursery', 'star_relay', 'lullaby_orbit'):
        points = 4+stage*2
        for i in range(round(points*density)):
            a = -math.pi/2+i*math.tau/points+p*.8
            _small_star(d, x+math.cos(a)*radius*.65, y+math.sin(a)*radius*.52,
                        4+stage, c[3 if i%2 else 4], 4, a)
    elif kind == 'song_wave':
        for i in range(round((4+stage)*density)):
            rr = radius*(.35+i*.17)
            d.arc((x-rr, y-rr*.6, x+rr, y+rr*.6), 190, 350, fill=c[3], width=3)
        _small_star(d, x, y-5, 4+stage, c[4], 5, p*3)
    elif kind in ('training_fist', 'venom_drill', 'boulder_roll'):
        for i in range(round((3+stage)*density)):
            a = p*4+i*2.399963
            _line(d, ((x, y), (x+math.cos(a)*radius*.75, y+math.sin(a)*radius*.65)), c[2], 4)
            _circle(d, (x+math.cos(a)*radius*.75, y+math.sin(a)*radius*.65), 3, c[4])
    elif kind == 'warp_spoon':
        for i in range(round((2+stage)*density)):
            rr = radius*(.45+i*.25)
            d.ellipse((x-rr, y-rr*.66, x+rr, y+rr*.66), outline=c[3], width=3)
        _circle(d, (x, y), 4, c[4])
    elif kind in ('venom_crescent', 'gas_lantern'):
        for side in (-1, 1):
            d.arc((x-radius*.75, y-radius*.55, x+radius*.75, y+radius*.55),
                  250 if side < 0 else 70, 20 if side < 0 else 200, fill=c[3], width=3)
        _circle(d, (x, y), 4+stage, c[2], outline=c[4])
    elif kind in ('silk_cocoon', 'moon_shell'):
        for i in range(round((5+stage*2)*density)):
            a = i*math.tau/(5+stage*2)
            _circle(d, (x+math.cos(a)*radius*.5, y+math.sin(a)*radius*.38), 3, c[3])
    elif kind == 'clamp_frost':
        for side in (-1, 1):
            d.arc((x+side*radius*.35-radius*.65, y-radius*.7, x+side*radius*.35+radius*.65, y+radius*.7),
                  250 if side < 0 else 70, 80 if side < 0 else 200, fill=c[2], width=3)
    elif kind == 'adaptive_ring':
        directions = 6+stage*2
        for i in range(round(directions*density)):
            a = i*math.tau/directions+p
            _line(d, ((x+math.cos(a)*5, y+math.sin(a)*5),
                      (x+math.cos(a)*radius*.72, y+math.sin(a)*radius*.6)), c[3], 3)
    elif kind == 'torrent_maw':
        for i in range(round((5+stage)*density)):
            a = i*math.tau/(5+stage)
            _line(d, ((x+math.cos(a)*8, y+math.sin(a)*6), (x+math.cos(a)*radius*.85, y+math.sin(a)*radius*.68)), c[2], 3)
    elif kind == 'frost_kiss':
        for i in range(round((5+stage)*density)):
            a = i*math.tau/(5+stage)
            _circle(d, (x+math.cos(a)*radius*.55, y+math.sin(a)*radius*.48), 3, c[3])
        _circle(d, (x, y), 4+stage, c[4])
    else:
        _circle(d, origin, radius*.55, c[2], width=3, outline=c[3])


def _landing(layer, d, sid, target, p, config, *, secondary=False):
    e = _entry(sid)
    c = rp.palette(e['element'], config)
    scale, density = rp.settings(config)
    stage = e['stage']
    local = scale*(.62 if secondary else 1.)
    radius = (17+stage*8+p*27)*local
    kind = e['cast_kind']
    x, y = target
    if kind in ('moon_shell', 'star_nursery', 'solar_seed', 'leaf_collar', 'aroma_bloom'):
        points = 5+stage*2
        for i in range(round(points*density)):
            a = -math.pi/2+i*math.tau/points+p*.5
            _small_star(d, x+math.cos(a)*radius*.68, y+math.sin(a)*radius*.55, 4+stage, c[3 if i%2 else 4], 4, a)
        _circle(d, target, radius*.5, c[2], width=3, outline=c[3])
    elif kind in ('tail_ember', 'ember_dash', 'vent_flare', 'flame_crown'):
        for i in range(round((6+stage*2)*density)):
            a = p*.8+i*math.tau/(6+stage*2)
            _line(d, ((x, y), (x+math.cos(a)*radius, y+math.sin(a)*radius*.72)), c[2 if i%2 else 3], 4)
        _circle(d, target, 5+stage, c[4])
    elif kind in ('shell_jet', 'dragon_current', 'water_veil', 'jaw_rush', 'tail_ripple', 'mud_pad'):
        for i in range(round((4+stage)*density)):
            rr = radius*(.34+i*.18)
            d.ellipse((x-rr, y-rr*.6, x+rr, y+rr*.6), outline=c[2+i%2], width=3)
    elif kind in ('cheek_bolt', 'pichu_spark', 'chain_arrow', 'plug_arc', 'twin_beacon', 'wool_charge'):
        for i in range(round((6+stage*2)*density)):
            a = i*math.tau/(6+stage*2)+p*.4
            _line(d, ((x+math.cos(a)*radius*.2, y+math.sin(a)*radius*.2),
                      (x+math.cos(a)*radius, y+math.sin(a)*radius*.75)), c[3 if i%2 else 2], 3)
            _circle(d, (x+math.cos(a)*radius, y+math.sin(a)*radius*.75), 3, c[4])
    elif kind in ('silk_cocoon', 'moon_shell'):
        for i in range(round((7+stage*2)*density)):
            a = i*math.tau/(7+stage*2)+p
            _circle(d, (x+math.cos(a)*radius*.7, y+math.sin(a)*radius*.55), 3, c[3])
    elif kind in ('training_fist', 'venom_drill', 'boulder_roll'):
        for i in range(round((6+stage*2)*density)):
            a = i*math.tau/(6+stage*2)
            _polygon(d, ((x+math.cos(a)*radius*.7, y+math.sin(a)*radius*.58),
                         (x+math.cos(a+.25)*(radius*.7+5), y+math.sin(a+.25)*(radius*.58+4)),
                         (x+math.cos(a-.25)*(radius*.7+5), y+math.sin(a-.25)*(radius*.58+4))), c[2 if i%2 else 3])
        d.line((x-radius*.4, y-radius*.25, x+radius*.4, y+radius*.25), fill=c[4], width=3)
    elif kind == 'warp_spoon':
        for i in range(round((3+stage)*density)):
            rr = radius*(.42+i*.2)
            d.ellipse((x-rr, y-rr*.6, x+rr, y+rr*.6), outline=c[3], width=3)
        _line(d, ((x-radius*.3, y), (x, y-radius*.25), (x+radius*.3, y)), c[4], 3)
    elif kind in ('venom_crescent', 'gas_lantern'):
        for side in (-1, 1):
            d.arc((x-radius*.8, y-radius*.55, x+radius*.8, y+radius*.55),
                  245 if side < 0 else 65, 25 if side < 0 else 205, fill=c[3], width=3)
        _circle(d, target, radius*.3, c[1] + (180,), outline=c[4])
    elif kind == 'clamp_frost':
        for side in (-1, 1):
            d.arc((x+side*radius*.35-radius*.7, y-radius*.7, x+side*radius*.35+radius*.7, y+radius*.7),
                  250 if side < 0 else 70, 80 if side < 0 else 200, fill=c[2], width=3)
        for i in range(round((5+stage)*density)):
            a = i*math.tau/(5+stage)
            _circle(d, (x+math.cos(a)*radius*.6, y+math.sin(a)*radius*.52), 3, c[4])
    elif kind in ('star_relay', 'lullaby_orbit'):
        for i in range(round((5+stage*2)*density)):
            q = ((p*1.2+i/(5+stage*2)) % 1.)
            at = (x+(i%(2+stage)-1)*(radius*.22), y-radius*q*.85)
            _small_star(d, *at, 3+stage, c[4 if i%2 else 3], 4, q*4)
    elif kind == 'song_wave':
        for i in range(round((6+stage*2)*density)):
            rr = radius*(.32+i*.14)
            d.ellipse((x-rr, y-rr*.58, x+rr, y+rr*.58), outline=c[3 if i%2 else 4], width=3)
        _small_star(d, x, y-radius*.35, 4+stage, c[4], 5, p*3)
    elif kind == 'adaptive_ring':
        directions = 8+stage*2
        for i in range(round(directions*density)):
            a = i*math.tau/directions
            _line(d, ((x+math.cos(a)*radius*.2, y+math.sin(a)*radius*.2),
                      (x+math.cos(a)*radius, y+math.sin(a)*radius*.76)), c[3], 3)
    elif kind == 'torrent_maw':
        _polygon(d, ((x-radius, y-radius*.22), (x-radius*.2, y-radius*.68), (x+radius, y),
                     (x+radius*.2, y+radius*.68), (x-radius, y+radius*.22)), c[2], outline=c[3])
        for i in range(round((6+stage*2)*density)):
            _line(d, ((x-radius*.7+i*radius*.22, y-radius*.3), (x-radius*.45+i*radius*.22, y+radius*.3)), c[4], 3)
    elif kind == 'splash_arc':
        _line(d, ((x-radius, y+radius*.25), (x, y-radius*.55), (x+radius, y+radius*.25)), c[3], 4)
        for i in range(round((5+stage)*density)):
            a = math.pi+i*math.pi/(4+stage)
            _circle(d, (x+math.cos(a)*radius*.75, y+radius*.25+math.sin(a)*radius*.35), 3, c[4])
    elif kind == 'frost_kiss':
        for i in range(6):
            a = i*math.tau/6+p*.4
            _line(d, ((x, y), (x+math.cos(a)*radius*.75, y+math.sin(a)*radius*.75)), c[3], 3)
            _circle(d, (x+math.cos(a)*radius*.75, y+math.sin(a)*radius*.75), 3, c[4])
    else:
        _circle(d, target, radius*.6, c[2], width=3, outline=c[3])
    # A bounded universal accent keeps density meaningful for fixed arcs too.
    accents = round((4+stage)*density)
    for i in range(max(0, accents)):
        a = i*math.tau/max(1, accents)+sid*.23
        at = (x+math.cos(a)*radius*.9, y+math.sin(a)*radius*.68)
        _polygon(d, ((at[0], at[1]-4), (at[0]+3, at[1]), (at[0], at[1]+4), (at[0]-3, at[1])), c[4])

def _attack_burst(layer, d, sid, target, p, config, *, secondary=False):
    e = _entry(sid)
    c = rp.palette(e['element'], config)
    scale, density = rp.settings(config)
    stage = e['stage']
    local = scale*(.66 if secondary else 1.)
    radius = (15+stage*7+p*20)*local
    x, y = target
    rays = round((6+stage*2)*density)
    for i in range(max(1, rays)):
        a = i*math.tau/max(1, rays)+sid*.17
        _line(d, ((x+math.cos(a)*radius*.3, y+math.sin(a)*radius*.25),
                  (x+math.cos(a)*radius, y+math.sin(a)*radius*.75)), c[3 if i%2 else 2], 3)
    _sprite(layer, sid, target, 62*local*(1-p*.18), .45+p*.55, a, config,
            alpha=1.-p*.7)


def _aftermath_scatter(d, sid, target, p, config):
    e = _entry(sid)
    c = rp.palette(e['element'], config)
    scale, density = rp.settings(config)
    stage = e['stage']
    x, y = target
    count = round((7+stage*2)*density)
    for i in range(max(1, count)):
        q = min(1., max(0., p*1.18-i*.035))
        a = i*2.399963+sid*.31
        radius = (17+q*62+(i%3)*8)*scale
        at = (x+math.cos(a)*radius, y+math.sin(a)*radius*.76-q*10*scale)
        size = 4 if i%3 else 6
        if e['element'] in ('FIRE', 'ELECTRIC'):
            _polygon(d, ((at[0], at[1]-size*1.5), (at[0]-size, at[1]),
                         (at[0], at[1]+size*.7), (at[0]+size, at[1])), c[3])
        elif e['element'] in ('GRASS', 'BUG', 'POISON'):
            _polygon(d, ((at[0]-size, at[1]+size*.4), (at[0], at[1]-size),
                         (at[0]+size, at[1]+size*.4)), c[2])
        else:
            _circle(d, at, size*.6, c[3])


def _render(layer, sid, source, target, phase, progress, config, *,
            kind='cast', emitters=(), secondary=False):
    """Draw the unquantized frame on the supplied layer.

    ``kind='attack'`` is the basic-attack track; ``kind='cast'`` is the native
    kit selected for this real species.  Emitters are replay-provided points;
    support and self casts still use their actual ``target``/caster coordinate.
    """
    if sid not in SPECIES or kind not in ('attack', 'cast'):
        return False
    if phase not in ('windup', 'flight', 'impact', 'aftermath'):
        return False
    try:
        p = float(progress)
    except (TypeError, ValueError):
        return False
    if not 0. <= p < 1.:
        return True
    cfg = config if isinstance(config, dict) else {}
    try:
        scale, density = rp.settings(cfg)
    except (TypeError, ValueError):
        cfg = {}
        scale, density = rp.settings(cfg)
    e = _entry(sid)
    colors = rp.palette(e['element'], cfg)
    stage = e['stage']
    a, b = tuple(source), tuple(target)
    angle = math.atan2(b[1]-a[1], b[0]-a[0])
    d = ImageDraw.Draw(layer)
    if secondary and phase in ('windup', 'flight'):
        return True

    if kind == 'attack':
        origins = tuple(emitters)[:1+stage] or (a,)
        if phase == 'windup':
            for i, origin in enumerate(origins):
                _sprite(layer, sid, origin, (36+stage*8+p*18)*scale,
                        p*.28+i*.05, angle+p*2, cfg, alpha=.72+p*.28)
            _charge(layer, d, sid, origins[0], p*.42, cfg)
        elif phase == 'flight':
            lane_count = min(len(origins), 1 if stage == 1 else 2)
            for lane in range(lane_count):
                origin = origins[lane]
                nx, ny = _normal(origin, b)
                offset = (lane-(lane_count-1)/2)*(7+stage*2)*scale
                start = origin[0]+nx*offset, origin[1]+ny*offset
                for i in range(max(1, round(3*density))):
                    q = max(0., p-i*.055)
                    at = _travel_point(start, b, q, e['cast_kind'], stage)
                    alpha = .20 if i else 1.
                    _sprite(layer, sid, at, (48+stage*10)*scale, .2+q*.2,
                            angle+q*2, cfg, alpha=alpha)
                    if i == 0:
                        route = [_travel_point(start, b, max(0., q-j/8), e['cast_kind'], stage)
                                 for j in range(9)]
                        _line(d, route, colors[2], 3+stage)
        elif phase == 'impact':
            _attack_burst(layer, d, sid, b, p, cfg, secondary=secondary)
        else:
            _aftermath_scatter(d, sid, b, p, cfg)
            _sprite(layer, sid, b, (64+stage*10)*scale*(1-p*.55), .72,
                    angle+3, cfg, alpha=(1-p)*.85)
        return True

    # Native kit: charge at real emitter/body points, travel to the recorded
    # target, then land there. Self/ally kits never invent extra recipients.
    origins = tuple(emitters)[:1+stage] or (a,)
    if phase == 'windup':
        for origin in origins:
            _charge(layer, d, sid, origin, p, cfg)
            _sprite(layer, sid, origin, (31+stage*7+p*20)*scale, p*.2,
                    angle+p*2.4, cfg, alpha=.55+p*.35)
    elif phase == 'flight':
        for lane, origin in enumerate(origins[:1 if stage == 1 else min(2, len(origins))]):
            nx, ny = _normal(origin, b)
            offset = (lane-(min(2, len(origins))-1)/2)*(9+stage*2)*scale
            start = origin[0]+nx*offset, origin[1]+ny*offset
            route = _cast_route(start, b, p, e['cast_kind'], stage)
            if e['cast_kind'] in ('cheek_bolt', 'pichu_spark', 'chain_arrow', 'plug_arc', 'twin_beacon'):
                for i, point in enumerate(route[1:-1]):
                    if i % 2 == 0:
                        _line(d, (route[i], point, route[i+2] if i+2 < len(route) else b), colors[3], 4)
            else:
                _line(d, route, colors[2], 4+stage)
            for i in range(max(1, round(2*density))):
                q = max(0., p-i*.05)
                at = _travel_point(start, b, q, e['cast_kind'], stage)
                _sprite(layer, sid, at, (54+stage*11)*scale, .18+q*.24,
                        angle+q*2.2, cfg, alpha=1. if i == 0 else .2)
    elif phase == 'impact':
        _landing(layer, d, sid, b, p, cfg, secondary=secondary)
        _sprite(layer, sid, b, (72+stage*12)*scale*(1-p*.12), .45+p*.55,
                angle+p*2.6, cfg, alpha=1.-p*.35)
    else:
        _aftermath_scatter(d, sid, b, p, cfg)
        _landing(layer, d, sid, b, min(1., p*.72), cfg, secondary=True)
        _sprite(layer, sid, b, (76+stage*12)*scale*(1-p*.58), .76,
                angle+3.2, cfg, alpha=(1-p)*.82)
    return True


def draw(layer, sid, source, target, phase, progress, config, *,
         kind='cast', emitters=(), secondary=False):
    """Render and quantize one frame to the shared three-pixel display grid."""
    # Render apart from the destination, then sample one pixel per display
    # cell and magnify it.  This keeps curves, alpha trails and impact rings
    # on the same grid as the authored native cels.
    surface = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    if not _render(surface, sid, source, target, phase, progress, config,
                   kind=kind, emitters=emitters, secondary=secondary):
        return False
    cells = surface.reduce(rp.PIXEL)
    quantized = cells.resize((cells.width*rp.PIXEL, cells.height*rp.PIXEL),
                             Image.Resampling.NEAREST)
    layer.alpha_composite(quantized.crop((0, 0, layer.width, layer.height)))
    return True
