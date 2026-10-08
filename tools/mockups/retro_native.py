"""Shared dispatch for native move art and its authoritative effect packets."""
import retro_moves
import retro_elemental
import retro_physical
import retro_support
from move_references import REFERENCES
from arena_skills import SKILLS

CONTACT_DURATION = .22
LIFETIME = .8
GROUPS = (('元素招式',retro_elemental),('近战与地形',retro_physical),
          ('治疗与保护',retro_support))
_OWNERS = {key:module for _,module in GROUPS for key in module.SKILL_IDS}
SKILL_IDS = frozenset((*_OWNERS,'flame_storm'))


def has_move(move):
    return isinstance(move,str) and move.startswith('arena_') and move[6:] in SKILL_IDS


def lifetime(move):
    return LIFETIME if has_move(move) else .5


def draw(layer, move, source, target, phase, progress, config, *, emitters=(),secondary=False,
         targeting=None, field_cells=()):
    if not has_move(move):
        return False
    key=move[6:]
    targeting = targeting or next((s.get('targeting', 'enemy') for s in SKILLS.values()
                                  if s['id'] == key), 'enemy')
    if not secondary and targeting == 'ally':
        return retro_support.draw_assistance(layer,key,source,target,phase,progress,config,emitters=emitters)
    if not secondary and targeting == 'self':
        return retro_support.draw_stance(layer,key,source,phase,progress,config)
    if not secondary and targeting == 'field' and key == 'rock_spikes':
        return retro_support.draw_field_cast(layer,source,field_cells or (target,),phase,progress,config)
    if key=='flame_storm':
        retro_moves.draw_fire_blast(layer,source,target,phase,progress,config,secondary=secondary)
        return True
    return _OWNERS[key].draw(layer,key,source,target,phase,progress,config,
                             emitters=emitters,secondary=secondary)


def effect_key(event, original_events):
    """A native-looking key alone is insufficient: verify the owning cast."""
    if len(event)!=7 or event[1]!='skill_effect' or not isinstance(event[6],dict):
        return None
    key=event[4]
    index=event[6].get('cast_index')
    if key not in SKILL_IDS or type(index) is not int or not 0<=index<len(original_events):
        return None
    owner=original_events[index]
    if len(owner)<5 or owner[1]!='cast' or owner[2]!=event[2] or owner[4]!='arena_'+key:
        return None
    return key


def draw_outcome(layer,key,effect,source,target,age,config,details):
    if not 0<=age<LIFETIME:
        return False
    if effect=='side_hit':
        if details.get('damage',0)<=0:
            return True
        phase='impact' if age<CONTACT_DURATION else 'aftermath'
        progress=(age/CONTACT_DURATION if age<CONTACT_DURATION else
                  (age-CONTACT_DURATION)/(LIFETIME-CONTACT_DURATION))
        return draw(layer,'arena_'+key,source,target,phase,progress,config,secondary=True)
    if effect=='heal' and details.get('amount',0)<=0:
        return False  # Preserve the explicit blocked-healing mark in the renderer.
    return retro_support.draw_outcome(layer,key,effect,source,target,age/LIFETIME,config,details)


def describe(key):
    if key not in SKILL_IDS:
        return None
    group=next((name for name,module in GROUPS if key in module.SKILL_IDS),'元素招式')
    skill = next(s for s in SKILLS.values() if s['id'] == key)
    return {'style':'掌机像素招式','group':group,'authored':True,
            'targeting':skill.get('targeting','enemy'),'category':skill.get('category'),
            'contact_duration':CONTACT_DURATION,'tail_duration':LIFETIME,
            'outcome_source':'authoritative_cast_packets',
            'reference': REFERENCES[key]}
