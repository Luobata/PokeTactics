"""Isolated arena action fixtures shared by the editor, range and exporters.

Every action is resolved by the real arena_v1/budget_v1 Battle. Initial injury,
energy, durable posts and deployment are training inputs; no damage, skill,
movement, death or outcome event is invented by this module.
"""
import copy
import random

from action_preview import PREVIEW_ACTIONS
from arena import build_templates
from combat import Battle
from data import ENERGY_MAX
import arena_skills
import status
from decoders import Front, Palettes, Font16
from render_battle_gif import BattleAnimation

SCENES = ('dummy', 'melee', 'ranged')


def make_preview_scene(species_id, kind, seed=7, visual_overrides=None, *, scene='dummy'):
    """Return a BattleAnimation with unit 0 as the selected arena character.

    Cast scenes have two injured friends and four durable enemies so healing,
    chains, splashes, forward-lane hits and displacement retain real recipients.
    Other scenes isolate one action. Ranged counterattack posts are two cells
    away; melee posts engage at contact distance. Idle delays the first action
    beyond the inspection window rather than fabricating an idle event.
    """
    templates = build_templates()
    if type(species_id) is not int or species_id not in templates:
        raise ValueError('请选择竞技上场池中的宝可梦')
    if not isinstance(kind, str) or kind not in PREVIEW_ACTIONS:
        raise ValueError(f'unsupported arena preview action: {kind}')
    if not isinstance(scene, str) or scene not in SCENES:
        raise ValueError(f'unsupported arena training scene: {scene}')
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError('种子必须为 0–4294967295 的整数')
    from web_battle import normalize_visual_overrides
    settings = normalize_visual_overrides(visual_overrides)
    post = {'dummy': 9, 'melee': 68, 'ranged': 121}[scene]
    # Cast recipients stay pure Water: none of the 17 elements is immune here.
    # Range scene labels still describe actual deployments and opponent art.
    enemies = [9] * 4 if kind == 'cast' else [post]
    friends = [species_id, 68, 31] if kind == 'cast' else [species_id]
    pa = [(2, 3), (1, 3), (3, 3)][:len(friends)]
    pb = [(2, 2), (1, 2), (3, 2), (2, 0)][:len(enemies)]
    if kind == 'cast' and scene == 'melee':
        pb = [(2, 2), (1, 2), (3, 2), (1, 1)]
    elif kind == 'cast' and scene == 'ranged':
        pa = [(2, 3), (1, 4), (3, 4)]
        pb = [(2, 2), (2, 0), (4, 0), (5, 1)]
    if kind in ('idle', 'move'):
        pa = [(1, 5)]
        pb = [{'dummy': (4, 0), 'melee': (1, 0), 'ranged': (5, 1)}[scene]]
    elif scene == 'ranged' and kind in ('hit', 'death'):
        pb = [(2, 1)]
    battle = Battle([copy.copy(templates[sid]) for sid in friends],
                    [copy.copy(templates[sid]) for sid in enemies], random.Random(seed),
                    positions_a=pa, positions_b=pb,
                    ruleset='arena_v1', stat_mode='budget_v1')
    hero = battle.units[0]
    primary = battle.units[len(friends)]
    for unit in battle.units:
        unit.max_hp *= 8
        unit.hp = unit.max_hp
        unit.energy = 0
        unit.next_act = 1e6
    hero.target_idx = primary.idx
    primary.target_idx = hero.idx
    if kind == 'cast':
        hero.hp = hero.max_hp * 3 // 4
        hero.energy = ENERGY_MAX
        primary.energy = 40
        for unit in battle.units[1:len(friends)]:
            unit.hp = unit.max_hp // 3
            unit.energy = 25 if unit.piece.role_key == 'attack' else 0
        if species_id == 65:
            battle.units[-1].hp //= 2  # Native psychic blink can select a real weakened enemy.
    elif kind == 'death':
        hero.hp = 1
    # These are the authoritative initial fixture records. All following
    # records are produced by _act, including field displacement and death.
    battle.events = [(0., 'deploy', unit.idx, unit.pos) for unit in battle.units]
    for unit in battle.units:
        battle._emit_state(unit, 0.)
    if kind == 'cast' and species_id in (12, 45, 113, 131, 154, 164):
        # A real initial status makes the cleanse identity inspectable. It is
        # applied through the status rules (no hand-authored outcome packet).
        status.apply_debuff(battle, battle.units[1],
                            'sleep' if species_id == 164 else 'freeze' if species_id == 131 else 'poison',
                            0., source=primary)
    actor = primary if kind in ('hit', 'death') else hero
    # A ranged post already has the native range to reach the two-cell target.
    # For ordinary attack/cast, selected units retain their real melee/ranged reach.
    onset = 2. if kind == 'idle' else .5
    battle.duration = onset
    battle._act(actor, onset)
    if kind == 'cast' and species_id == 31:
        # The stance has no hit on activation. One actual incoming melee action
        # exposes the bounded retaliation rather than inventing a side projectile.
        battle._act(primary, onset + .90)
    casts = [event for event in battle.events if event[1] == 'cast' and event[2] == hero.idx]
    recipient = casts[0][3] if kind == 'cast' and casts else primary.idx
    anim = BattleAnimation([], [], seed, Front(), Palettes(), Font16(), battle=battle)
    anim.web_visual_overrides = settings
    anim.preview_fixture = {'mode': 'arena', 'scene': scene,
                            'ruleset': 'arena_v1', 'stat_mode': 'budget_v1',
                            'selected_unit': 0, 'primary_target': recipient,
                            'opponent_anchor': primary.idx,
                            'targeting': arena_skills.SKILLS[species_id].get('targeting', 'enemy') if kind == 'cast' else 'enemy',
                            'reactive_probe': kind == 'cast' and species_id == 31,
                            'initial_injury': kind == 'cast', 'action_onset': onset,
                            'native_skill': kind == 'cast'}
    return anim
