"""Local body cues inspired by original palette/scale animation tasks.

Pure visual transforms: no state mutation, extra hit, movement or clock retiming.
"""
import math
from PIL import Image

PSYCHIC = frozenset(('psychic_blink', 'slow_field', 'fracture_vision'))


def body_cue(key, progress, *, receiving=False, motion_scale=1., weight=1.):
    """Return scale and palette pulse; progress is relative to a real action."""
    if not 0 <= progress < 1:
        return 1., 1., None, 0.
    if receiving:
        # Hold the compressed impact pose for 55ms, then recover within 240ms.
        # Heavier hits compress further and flash brighter, within caps.
        strength = 1. if progress < .23 else (1-progress)/.77
        amount = strength * motion_scale * weight
        if key in PSYCHIC:
            return (1+.14*amount, 1-.15*amount, (222, 169, 255),
                    min(.55, .42*strength*weight))
        return (1+.07*amount, 1-.09*amount, (255, 247, 208),
                min(.5, .38*strength*weight))
    wave = math.sin(progress*math.pi)
    if key == 'psychic_blink':
        return 1-.23*wave*motion_scale, 1+.24*wave*motion_scale, (207, 155, 243), .25*wave
    if key == 'venom_armor':
        return 1+.16*wave*motion_scale, 1-.23*wave*motion_scale, (178, 115, 219), .23*wave
    return 1., 1., None, 0.


def transform_body(sprite, cue):
    """Keep foot and rig attachments registered, and never mutate cached art."""
    sx, sy, color, amount = cue
    if sx == sy == 1 and not amount:
        return sprite
    result = sprite.resize((max(1, round(sprite.width*sx)), max(1, round(sprite.height*sy))),
                           Image.Resampling.NEAREST)
    rx, ry = result.width/sprite.width, result.height/sprite.height
    info = dict(sprite.info)
    if 'foot_anchor' in info:
        info['foot_anchor'] = (info['foot_anchor'][0]*rx, info['foot_anchor'][1]*ry)
    if 'rig_anchors' in info:
        info['rig_anchors'] = {name:(x*rx,y*ry) for name,(x,y) in info['rig_anchors'].items()}
    if color and amount:
        alpha = result.getchannel('A')
        result = Image.blend(result, Image.new('RGBA', result.size, (*color,255)), amount)
        result.putalpha(alpha)
    result.info = info
    return result
