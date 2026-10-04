"""Authored single-cel animation: 10 Hz idle, 20 Hz retimed actions. No simulation state is mutated.

Frames are (forward_px, down_px, scale_x_percent, scale_y_percent,
clockwise_degrees, dissolve_quarters). Local rigs move integer source slices;
NEAREST resampling and ordered dissolve preserve the source palette/1-bit alpha.
Missing species return None: the renderer must execute its original branch.
"""
from dataclasses import dataclass
import math
from PIL import Image, ImageDraw, ImageOps
from character_rigs import implemented as has_character_rig, render_rig, _point_after_rotation

REST = (0, 0, 100, 100, 0, 0)
# Every sequence is authored, including recovery/hit/death; no ID-derived seeds.
species_motion = {
 6: {
 'idle': [REST,(0,-1,100,98,-1,0),(0,-2,98,100,0,0),(0,-1,100,100,1,0),REST,(0,0,100,98,0,0)],
 'walk': [(0,-1,96,100,-3,0),(1,-3,100,96,0,0),(0,-2,98,100,3,0),(-1,0,100,98,0,0)],
 'windup': [(-1,0,100,98,-3,0),(-2,-1,98,103,-5,0),(-2,-2,96,105,-6,0)],
 'strike': [(3,0,103,94,4,0),(2,1,102,96,2,0)],
 'recover': [(1,0,100,98,1,0),REST,(0,-1,100,100,0,0)],
 'hit': [(-1,0,97,103,-2,0),(0,1,100,98,1,0),REST],
 'death': [(0,1,100,96,2,0),(0,2,100,92,4,0),(0,3,98,88,6,1),(0,4,96,82,8,2),(0,5,94,76,9,3),(0,6,90,70,10,3)]},
 65: {
 'idle': [REST,(0,-1,100,100,0,0),(0,-2,98,102,0,0),(0,-2,100,100,0,0),(0,-1,102,98,0,0),REST,(0,1,100,100,0,0),REST],
 'walk': [(0,-1,98,102,-1,0),(1,-2,100,100,0,0),(2,-2,102,98,1,0),(1,-1,100,100,0,0)],
 'windup': [(0,-1,98,102,0,0),(0,-2,96,104,0,0),(0,-3,94,105,0,0),(0,-3,96,103,0,0)],
 'strike': [(2,-2,104,96,0,0),(1,-1,102,98,0,0)],
 'recover': [(0,-2,98,102,0,0),(0,-1,100,100,0,0),REST],
 'hit': [(-1,-1,96,104,-3,0),(-1,0,98,102,2,0),REST],
 'death': [(0,-1,98,100,0,0),(0,-2,94,100,0,1),(0,-3,90,98,0,1),(0,-4,86,96,0,2),(0,-5,80,94,0,3),(0,-6,76,90,0,3)]},
 143: {
 'idle': [REST,REST,REST,REST,(0,0,102,99,0,0),(0,0,102,99,0,0),(0,0,103,98,0,0),(0,0,103,98,0,0),(0,0,102,99,0,0),(0,0,102,99,0,0),REST,REST,REST,REST,(0,1,100,97,0,0),(0,1,100,97,0,0)],
 'walk': [(-1,0,100,98,-4,0),(-1,1,103,95,-2,0),(1,0,100,98,4,0),(1,1,103,95,2,0),REST],
 'windup': [(-1,1,102,96,-2,0),(-2,1,103,95,-4,0),(-2,0,100,102,-5,0),(0,-1,98,104,0,0)],
 'strike': [(3,2,105,88,5,0),(2,2,104,92,3,0)],
 'recover': [(1,2,103,94,2,0),(0,1,102,97,0,0),REST,REST],
 'hit': [(0,1,100,98,1,0),(1,0,100,100,-1,0),REST],
 'death': [(0,1,104,92,0,0),(0,3,105,84,0,0),(0,5,105,74,0,1),(0,6,105,64,0,1),(0,7,104,54,0,2),(0,8,104,44,0,3)]},
 149: {
 'idle': [REST,(0,-1,101,99,-2,0),(0,0,100,101,0,0),(0,-1,99,100,2,0),REST],
 'walk': [(-1,1,103,96,-5,0),(0,-2,98,104,-2,0),(2,-1,100,100,4,0),(1,1,103,95,2,0),REST],
 'windup': [(-1,1,103,97,-4,0),(-2,0,101,101,-8,0),(-2,-1,98,104,-10,0)],
 'strike': [(3,-1,104,94,10,0),(3,1,103,95,6,0)],
 'recover': [(1,1,101,98,4,0),(0,0,100,100,-2,0),REST],
 'hit': [(1,0,99,100,-2,0),(-1,1,100,99,1,0),REST],
 'death': [(0,1,102,95,4,0),(0,2,104,90,8,0),(1,3,103,84,12,1),(1,4,102,76,14,2),(1,5,100,68,16,3),(1,6,98,60,18,3)]},
 9: {
 'idle': [REST,REST,(0,0,101,98,-1,0),(0,1,102,97,0,0),(0,0,101,99,1,0),REST],
 'walk': [(-1,1,102,96,-3,0),(0,0,100,100,0,0),(1,1,102,96,3,0),(0,0,99,101,0,0)],
 'windup': [(-1,1,103,96,-2,0),(-1,0,102,99,-4,0),(-2,0,101,101,-5,0)],
 'strike': [(2,1,104,94,3,0),(3,1,103,96,2,0)],
 'recover': [(-1,1,103,96,-2,0),(0,1,101,99,0,0),REST],
 'hit': [(1,0,100,99,0,0),(-1,0,100,100,0,0),REST],
 'death': [(0,1,102,95,-2,0),(0,2,104,87,-4,0),(0,4,104,79,-5,1),(0,5,103,71,-6,2),(0,6,102,63,-7,3),(0,7,100,55,-8,3)]},
 3: {
 'idle': [REST,(0,0,101,99,1,0),(0,-1,102,100,2,0),(0,0,101,101,0,0),(0,1,100,99,-2,0),REST],
 'walk': [(-1,1,102,96,-2,0),(1,0,100,102,1,0),(1,1,102,97,2,0),(-1,0,100,101,-1,0)],
 'windup': [(0,1,102,97,0,0),(0,0,101,101,-1,0),(0,-1,100,104,-2,0),(0,-2,98,106,0,0)],
 'strike': [(2,1,104,95,2,0),(2,0,102,98,1,0)],
 'recover': [(0,1,102,98,-1,0),(0,0,101,100,0,0),REST],
 'hit': [(1,1,101,98,1,0),(0,0,100,99,-1,0),REST],
 'death': [(0,1,102,94,1,0),(0,2,104,86,2,0),(0,3,105,78,1,1),(0,4,105,68,0,1),(0,5,104,58,0,2),(0,6,103,48,0,3)]},
 94: {
 'idle': [(0,0,100,100,-2,0),(0,1,103,97,0,1),(0,2,104,96,2,1),(0,1,101,99,0,0),(0,-1,97,103,-1,0)],
 'walk': [(1,0,104,96,-4,1),(2,-1,100,100,0,0),(1,-2,96,104,4,1),(0,-1,100,100,0,0)],
 'windup': [(-1,1,105,94,-5,0),(-2,0,103,97,-7,1),(-2,-1,100,103,-9,0)],
 'strike': [(3,0,106,92,7,0),(2,1,104,94,4,1)],
 'recover': [(0,1,102,98,2,1),(-1,0,99,101,-2,0),REST],
 'hit': [(-1,-1,92,107,-5,1),(0,1,105,95,3,2),REST],
 'death': [(0,0,102,98,0,1),(0,0,100,100,0,1),(0,0,98,102,0,2),(0,0,96,104,0,2),(0,0,94,106,0,3),(0,0,92,108,0,3)]},
 131: {
 'idle': [REST,(0,1,101,99,-1,0),(1,0,100,101,0,0),(0,-1,99,102,1,0),(-1,0,100,100,0,0),REST],
 'walk': [(1,0,102,98,-3,0),(2,-1,101,99,-1,0),(1,-2,99,102,2,0),(-1,-1,100,100,3,0),(-1,0,102,98,0,0)],
 'windup': [(-1,0,100,102,-2,0),(-1,-1,98,104,-4,0),(-2,-2,97,106,-6,0)],
 'strike': [(3,-1,103,96,5,0),(2,0,102,98,3,0)],
 'recover': [(1,1,101,99,2,0),(0,0,100,101,-1,0),REST],
 'hit': [(1,1,99,101,-1,0),(0,0,101,99,1,0),REST],
 'death': [(0,1,101,96,-3,0),(0,2,102,90,-6,0),(0,3,103,84,-9,1),(0,4,103,78,-12,2),(0,5,102,72,-14,3),(0,6,101,66,-16,3)]},
 59: {
 'idle': [REST,(0,-1,100,101,-1,0),(1,0,101,99,1,0),REST,(0,0,99,101,0,0)],
 'walk': [(1,-1,104,94,-5,0),(2,-3,98,103,-1,0),(1,-1,96,105,4,0),(-1,1,105,93,1,0)],
 'windup': [(-1,1,104,95,-4,0),(-2,0,101,102,-7,0)],
 'strike': [(3,-1,106,91,6,0),(2,0,104,95,3,0)],
 'recover': [(1,1,102,97,1,0),(-1,0,100,101,-1,0),REST],
 'hit': [(-1,1,95,104,-4,0),(0,-1,102,97,2,0),REST],
 'death': [(0,-1,100,98,-4,0),(-1,-2,98,96,-8,1),(-1,-3,96,94,-12,1),(-1,-4,94,92,-16,2),(-1,-5,92,90,-20,3),(-1,-6,90,88,-24,3)]},
 130: {
 'idle': [REST,(1,-1,99,102,-2,0),(0,-2,98,104,0,0),(-1,-1,101,101,2,0),(0,0,102,98,1,0),REST],
 'walk': [(-1,0,103,96,-6,0),(0,-2,98,104,-3,0),(2,-3,96,106,3,0),(1,-1,102,98,6,0),REST],
 'windup': [(-1,1,103,97,-5,0),(-2,-1,98,105,-8,0),(-2,-2,95,108,-10,0),(0,-3,97,106,-6,0)],
 'strike': [(3,1,105,92,9,0),(3,2,104,94,5,0)],
 'recover': [(1,1,102,98,3,0),(0,-1,99,103,-2,0),REST],
 'hit': [(1,0,98,102,-3,0),(0,1,101,99,2,0),REST],
 'death': [(0,1,102,94,5,0),(1,2,104,86,10,0),(1,3,105,78,15,1),(1,4,104,70,20,2),(1,5,102,62,25,3),(1,6,100,54,30,3)]},
 31: {
 'idle': [REST,(0,0,102,98,0,0),(0,1,101,99,-1,0),REST,(0,0,100,101,1,0),REST],
 'walk': [(-1,1,103,95,-4,0),(-1,0,99,102,-1,0),(1,1,102,96,4,0),(1,0,100,101,1,0)],
 'windup': [(-1,1,102,97,-3,0),(-2,0,101,100,-5,0),(-2,-1,99,103,-7,0)],
 'strike': [(2,1,104,95,6,0),(3,0,102,97,3,0)],
 'recover': [(1,1,101,99,2,0),(0,1,100,99,-1,0),REST],
 'hit': [(1,0,101,99,-1,0),(0,1,100,98,1,0),REST],
 'death': [(0,1,102,96,-2,0),(0,2,103,88,-4,0),(0,3,104,80,-6,1),(0,4,104,72,-8,1),(0,5,103,64,-10,2),(0,6,102,56,-12,3)]},
 34: {
 'idle': [REST,(1,0,100,101,2,0),(0,-1,99,102,0,0),(-1,0,101,99,-2,0),REST],
 'walk': [(-1,0,102,98,-6,0),(0,-1,98,104,-2,0),(2,1,104,95,5,0),(1,0,100,101,2,0)],
 'windup': [(-1,0,102,98,-6,0),(-2,-1,99,104,-10,0)],
 'strike': [(3,-1,105,94,12,0),(3,1,104,96,6,0)],
 'recover': [(1,1,102,98,3,0),(0,0,99,102,-3,0),REST],
 'hit': [(1,1,99,101,-2,0),(-1,0,101,99,2,0),REST],
 'death': [(0,1,102,94,3,0),(0,2,103,86,6,0),(1,3,104,78,9,1),(1,4,104,70,12,1),(1,5,103,62,15,2),(1,6,102,54,18,3)]},
 76: {
 'idle': [REST,REST,(0,1,103,97,0,0),(0,0,101,99,-1,0),REST,(0,0,101,99,1,0)],
 'walk': [(0,1,100,98,-10,0),(1,0,100,100,-20,0),(1,-1,100,100,10,0),(0,1,102,96,20,0)],
 'windup': [(0,1,104,94,0,0),(-1,2,105,90,-3,0),(-1,1,104,94,-5,0),(0,-2,96,105,0,0)],
 'strike': [(2,3,107,86,2,0),(3,2,105,90,0,0)],
 'recover': [(1,2,104,94,-2,0),(0,1,102,97,1,0),REST],
 'hit': [(1,0,100,100,1,0),(-1,0,100,100,-1,0),REST],
 'death': [(0,1,104,92,0,0),(0,2,106,82,0,0),(0,4,106,72,0,1),(0,6,105,62,0,2),(0,7,104,52,0,3),(0,8,103,42,0,3)]},
 95: {
 'idle': [REST,(1,0,99,102,-1,0),(0,-1,98,104,0,0),(-1,0,100,101,1,0),(0,1,102,98,0,0),REST],
 'walk': [(-1,1,103,97,-4,0),(1,0,99,104,-2,0),(2,-1,97,106,2,0),(0,1,104,96,4,0)],
 'windup': [(-1,1,102,98,-3,0),(-2,0,100,103,-6,0),(-2,-2,96,108,-9,0)],
 'strike': [(3,2,105,91,8,0),(2,1,103,95,4,0)],
 'recover': [(1,1,101,99,2,0),(0,-1,98,103,-2,0),REST],
 'hit': [(1,0,99,101,0,0),(0,1,101,99,0,0),REST],
 'death': [(0,1,102,93,-2,0),(0,3,104,83,-4,0),(0,5,105,73,-6,1),(0,6,105,63,-8,2),(0,7,104,53,-10,3),(0,8,103,43,-12,3)]},
 18: {
 'idle': [REST,(1,0,100,99,2,0),(0,-1,98,102,0,0),(-1,0,100,99,-2,0),REST,(0,1,102,98,0,0)],
 'walk': [(0,-2,94,103,-4,0),(1,-3,103,94,0,0),(2,-1,96,102,4,0),(0,0,104,93,0,0)],
 'windup': [(-1,0,96,104,-6,0),(-2,-2,94,106,-10,0)],
 'strike': [(3,-1,107,90,9,0),(2,0,104,94,5,0)],
 'recover': [(0,-2,97,103,2,0),(-1,-1,100,100,-2,0),REST],
 'hit': [(-1,-1,94,106,-6,0),(0,0,102,97,3,0),REST],
 'death': [(0,-1,98,100,6,0),(1,-2,96,98,12,1),(1,-3,94,96,18,1),(1,-4,92,94,24,2),(1,-5,90,92,30,3),(1,-6,88,90,36,3)]},
 26: {
 'idle': [REST,(1,0,99,101,-2,0),(-1,-1,101,99,2,0),REST,(1,0,100,99,1,0),(-1,0,99,100,-1,0)],
 'walk': [(1,-2,96,105,-5,0),(2,0,105,93,3,0),(-1,-1,98,104,-3,0),(1,1,104,95,5,0)],
 'windup': [(-1,1,104,94,-4,0),(-2,0,99,104,-8,0),(-2,-1,96,106,-10,0)],
 'strike': [(3,-1,106,92,8,0),(2,1,104,94,4,0)],
 'recover': [(1,0,99,102,2,0),(-1,0,102,98,-2,0),REST],
 'hit': [(-1,-1,93,107,-7,0),(-1,1,104,94,4,0),REST],
 'death': [(0,-1,99,101,-5,0),(-1,-2,97,99,-10,1),(-1,-3,95,97,-15,1),(-1,-4,93,95,-20,2),(-1,-5,91,93,-25,3),(-1,-6,89,91,-30,3)]},
}

# Retiming preserves the authored keys, amplitude and order. Insert integer
# in-betweens at 20 Hz; keep dissolve discrete and hold the last non-loop key.
# RIG_PHASES retain the original local-part phase instead of speeding up wings
# and tails when the whole-body sequence gains frames.
KEYFRAMES = {sid: {state: tuple(frames) for state, frames in states.items()}
             for sid, states in species_motion.items()}
SLOWDOWN = {'walk': 1.5, 'windup': 1.3, 'strike': 1.3,
            'recover': 1.3, 'hit': 4/3, 'death': 1.25}
RIG_PHASES = {}
for _sid, _states in species_motion.items():
    RIG_PHASES[_sid] = {}
    for _state, _keys in KEYFRAMES[_sid].items():
        if _state == 'idle':
            RIG_PHASES[_sid][_state] = tuple(range(len(_keys)))
            continue
        _count = round(len(_keys) * 2 * SLOWDOWN[_state])
        _frames, _phases = [], []
        for _i, _key in enumerate(_keys):
            _steps = round((_i+1)*_count/len(_keys)) - round(_i*_count/len(_keys))
            _next = (_i+1) % len(_keys) if _state == 'walk' else min(_i+1, len(_keys)-1)
            for _j in range(_steps):
                _mix = _j / _steps
                _frames.append(tuple(round(a+(b-a)*_mix) for a,b in zip(_key[:5], _keys[_next][:5])) + (_key[5],))
                _phases.append(_i + _mix if _next != _i else float(_i))
        _states[_state] = _frames
        RIG_PHASES[_sid][_state] = tuple(_phases)


def frame_dt(state):
    return .1 if state == 'idle' else .05


def duration(sid, state):
    return len(species_motion[sid][state]) * frame_dt(state)


def rig_phase(sid, state, index):
    return RIG_PHASES[sid][state][index]


# Region cuts in percent of the occupied sprite, with a separate phase track.
# Each tuple = (left, top, right, bottom, dx_track, dy_track). Crops are made
# from the original cel. Internal attachments extend the nearest edge pixel;
# all cuts are cleared before compositing, so transparent tiles cannot erase
# neighbours and a translated cut cannot leave a rectangular hole in the body.
RIGS = {
 6: ((0,12,30,70,(0,-1,0,1),(0,-2,0,1)),(70,12,100,70,(0,1,0,-1),(0,-2,0,1))),
 65: ((0,28,26,73,(0,-1,-1,0),(0,-1,-2,-1)),(74,28,100,73,(0,1,1,0),(0,-1,-2,-1))),
 143: ((24,40,77,88,(0,0,0,0,0,0,1,1,1,0,0,0,0,0,0,0),(0,0,0,0,-1,-1,-1,-1,-1,-1,0,0,0,0,0,0)),),
 149: ((0,18,24,59,(0,-1,0,0),(0,-1,1,0)),(70,60,100,100,(0,1,0,-1),(0,0,1,0))),
 9: ((10,10,36,39,(0,0,-1,0),(0,-1,0,0)),(63,10,91,39,(0,0,1,0),(0,-1,0,0))),
 3: ((18,0,84,44,(0,1,0,-1),(0,-1,0,1)),(0,73,35,100,(0,1,0,-1),(0,0,-1,0))),
 94: ((0,60,100,100,(0,1,-1,0),(0,-1,0,1)),),
 131: ((35,0,78,55,(0,-1,0,1),(0,0,-1,0)),(0,72,34,100,(0,1,0,-1),(0,-1,0,1))),
 59: ((0,70,40,100,(0,2,-1,-2),(0,-1,0,1)),(58,68,100,100,(0,-2,1,2),(0,1,0,-1))),
 130: ((0,0,100,32,(0,1,0,-1),(0,-1,0,1)),(0,32,100,64,(0,-1,0,1),(0,0,1,0)),(0,64,100,100,(0,1,0,-1),(0,1,0,-1))),
 31: ((0,62,36,100,(0,-1,0,1),(0,1,0,-1)),(66,32,100,68,(0,0,1,0),(0,-1,0,0))),
 34: ((28,0,65,31,(0,-1,1,0),(0,-1,0,1)),(66,63,100,100,(0,1,0,-1),(0,0,1,0))),
 76: ((0,31,24,73,(0,-1,0,1),(0,1,0,-1)),(76,31,100,73,(0,1,0,-1),(0,-1,0,1))),
 95: ((0,0,100,25,(0,1,0,-1),(0,0,-1,0)),(0,25,100,50,(1,0,-1,0),(0,0,0,0)),(0,50,100,75,(0,-1,0,1),(0,0,0,0)),(0,75,100,100,(-1,0,1,0),(0,0,1,0))),
 18: ((0,28,34,76,(0,-1,1,0),(0,-2,1,0)),(65,28,100,76,(0,1,-1,0),(0,-2,1,0)),(35,0,66,26,(0,1,0,0),(0,1,0,-1))),
 26: ((0,4,25,35,(0,1,-1,0),(0,-1,0,1)),(72,42,100,100,(0,-1,1,0),(0,1,-1,0))),
}

@dataclass(frozen=True)
class Pose:
    state: str
    index: int
    frame: tuple
    direction: tuple = (1., 0.)
    hit: tuple = REST
    hit_direction: tuple = (1., 0.)
    action_kind: str = None


def windup(sid):
    return duration(sid, 'windup')


def sample(sid, state, age):
    frames = species_motion[sid][state]
    index = max(0, math.floor((age + 1e-8) / frame_dt(state)))
    index = index % len(frames) if state in ('idle', 'walk') else min(index, len(frames)-1)
    return index, frames[index]


class MotionSystem:
    """Resolve past attack/cast/move/hit/death events at simulation clock time.

    Cast release uses the renderer's cinematic clock; basic attack has an authored
    preparation, then strike and recovery. Hit is an independent additive track.
    Freeze samples at status onset; death always takes priority over freeze.
    """
    @staticmethod
    def resolve(anim, au, t):
        sid = au.u.piece.species_id
        if sid not in species_motion:
            return None
        if 'freeze' in au.statuses and not au.dying(t):
            t = min(t, au.statuses['freeze'])
        strike_length = duration(sid, 'strike')
        release_length = strike_length + duration(sid, 'recover')
        state, age, direction = 'idle', t, (1. if au.u.team == 0 else -1., 0.)
        action_kind = None
        if au.dying(t):
            state, age = 'death', t - au.die_t
        else:
            candidates = [(c[0], anim._cast_release(c)-c[0], c[3]) for c in reversed(anim.cutins)
                          if c[2] == au.u.idx and c[0] <= t < anim._cast_release(c)+release_length]
            attack = next((a for a in reversed(au.attacks)
                           if 0 <= t-a[0] < anim._attack_preparation(au.u.idx, a[0])+release_length), None)
            if candidates and (attack is None or candidates[0][0] >= attack[0]):
                action_kind = 'cast'
                onset, prep, target = candidates[0]
                a, b = anim._event_position(au.u.idx,onset), anim._event_position(target,onset)
                dx, dy = b[0]-a[0], b[1]-a[1]
                norm = math.hypot(dx,dy) or 1
                direction = dx/norm,dy/norm
            elif attack:
                action_kind = 'attack'
                onset, dx, dy = attack
                prep, direction = anim._attack_preparation(au.u.idx, onset), (dx,dy)
            else:
                onset = None
            if onset is not None:
                elapsed = t-onset
                if elapsed < prep-1e-8:
                    state, age = 'windup', min(elapsed * windup(sid) / prep, windup(sid)-.001)
                elif elapsed < prep+strike_length-1e-8:
                    state, age = 'strike', elapsed-prep
                else:
                    state, age = 'recover', elapsed-prep-strike_length
            elif 0 <= t-au.move_t0 < duration(sid, 'walk'):
                state, age = 'walk', t-au.move_t0
        index, frame = sample(sid,state,age)
        hit, hit_dir = REST, direction
        if state != 'death':
            impacts = [(e[0]+anim._attack_delay(e), e[2]) for e in anim._recent_hits(t)
                       if e[3] == au.u.idx]
            impacts += [(c[1],c[2]) for c in anim.cutins
                        if c[3] == au.u.idx and c[6] > 0 and 0 <= t-c[1] < duration(sid, 'hit')]
            if impacts:
                at, attacker = max(impacts)
                _, hit = sample(sid,'hit',t-at)
                a,b = anim._event_position(attacker,at), au.render_px(t)
                dx,dy = a[0]-b[0],a[1]-b[1]
                norm = math.hypot(dx,dy) or 1
                hit_dir = dx/norm,dy/norm
        pose = Pose(state,index,frame,direction,hit,hit_dir,action_kind)
        return presentation_pose(sid, pose, anim.visual_config(sid)['motion_scale']) if getattr(anim, '_is_presentation', False) else pose


def presentation_pose(sid, pose, motion_scale=1.):
    """Readable native-pixel anticipation/overshoot, then an authored recovery.

    This affects the visual pose only. Identity comes from distinct body mechanics:
    Charizard leans into its breath, Alakazam levitates steadily, Snorlax compresses
    before the heavy release. Integer source slices and NEAREST stay unchanged.
    """
    forward, down, sx, sy, angle, dissolve = pose.frame
    if pose.state in ('windup', 'strike', 'recover'):
        factor = {6: 1.8, 9: 1.4, 3: 1.2, 26: 1.8, 65: 1.35, 94: 1.7, 76: 1.6, 143: 2.0}.get(sid, 1.25)
        factor *= .65 if pose.state == 'recover' else 1.
        forward = round(forward * factor)
        if sid == 143:
            if pose.state == 'windup':
                progress = pose.index/max(1,len(species_motion[sid]['windup'])-1)
                if progress < .65:
                    down, sx, sy = 3, 108, 84  # planted crouch: load the body weight
                else:
                    down, sx, sy = -5, 96, 106  # lift before the heavy contact
            elif pose.state == 'strike':
                down, sx, sy = 5, 110, 84
            elif pose.state == 'recover':
                down = min(2, down)
        elif sid == 65:
            down -= 1 if pose.state == 'windup' else 0
        elif sid == 6:
            angle = round(angle * 1.35)
        elif sid == 9:  # brace the shell, then push back under cannon recoil
            if pose.state == 'windup':
                down, sx, sy = 2, 105, 93
                forward -= 2
            elif pose.state == 'strike':
                forward, down, angle = -4, 2, -3
        elif sid == 3:  # flower lifts above a low, firmly planted body
            if pose.state == 'windup':
                down, sx, sy = -2, 97, 104
            elif pose.state == 'strike':
                down, sx, sy = 2, 105, 94
        elif sid == 26:  # crouched charge, quick whole-body extension
            if pose.state == 'windup':
                down, sx, sy = 2, 108, 90
            elif pose.state == 'strike':
                down, sx, sy, angle = -3, 94, 108, 4
        elif sid == 94:  # low floating curl opens into a lateral lunge
            if pose.state == 'windup':
                down, sx, sy, angle = -2, 91, 108, -4
            elif pose.state == 'strike':
                forward, sx, sy = 5, 113, 91
        elif sid == 76:  # squat rock mass drops into the ground wave
            if pose.state == 'windup':
                down, sx, sy = -3, 98, 103
            elif pose.state == 'strike':
                down, sx, sy = 5, 112, 87
    h = pose.hit
    hit = (round(h[0]*2), round(h[1]*1.5), h[2], h[3], h[4], h[5])
    frame = (round(forward*motion_scale), round(down*motion_scale),
             round(100+(sx-100)*motion_scale), round(100+(sy-100)*motion_scale),
             round(angle*motion_scale), dissolve)
    hit = (round(hit[0]*motion_scale), round(hit[1]*motion_scale),
           round(100+(hit[2]-100)*motion_scale), round(100+(hit[3]-100)*motion_scale),
           round(hit[4]*motion_scale), hit[5])
    return Pose(pose.state, pose.index, frame, pose.direction, hit, pose.hit_direction, pose.action_kind)


def offsets(pose):
    f,h = pose.frame,pose.hit
    return (f[0]*pose.direction[0] + h[0]*pose.hit_direction[0],
            f[1]+f[0]*pose.direction[1]+h[1]+h[0]*pose.hit_direction[1])


def rig_cel(cel, sid, index, next_index=None):
    """Translate parts with edge extrusion only at their internal attachments.

    The silhouette-facing edge is free to move. A vacated internal edge uses
    its original boundary row/column (including alpha), never a solid fill or
    a copy of the entire old part. Clear all source cuts before drawing any
    part, especially the adjacent rock/snake segments.
    """
    w, h = cel.size
    out = cel.copy()
    parts = []
    for left, top, right, bottom, xs, ys in RIGS[sid]:
        box = (left*w//100, top*h//100, right*w//100, bottom*h//100)
        tile = cel.crop(box)
        key = math.floor(index)
        mix = index - key
        dx, dy = (round(track[key % len(track)] * (1-mix) +
                        track[(key+1 if next_index is None else next_index) % len(track)] * mix) for track in (xs, ys))
        out.paste((0, 0, 0, 0), box)
        # Extend only the strip exposed by translation at an internal cut.
        l = dx if dx > 0 and box[0] > 0 else 0
        rr = -dx if dx < 0 and box[2] < w else 0
        t = dy if dy > 0 and box[1] > 0 else 0
        b = -dy if dy < 0 and box[3] < h else 0
        expanded = Image.new('RGBA', (tile.width+l+rr, tile.height+t+b))
        src, dst = tile.load(), expanded.load()
        for y in range(expanded.height):
            for x in range(expanded.width):
                dst[x, y] = src[min(tile.width-1, max(0, x-l)),
                                min(tile.height-1, max(0, y-t))]
        parts.append((expanded, (box[0]+dx-l, box[1]+dy-t)))
    for tile, position in parts:
        out.alpha_composite(tile, position)
    return out


def transform(sprite, sid, pose):
    """Pure cel synthesis; cache this at the renderer boundary, never modify input."""
    frame = pose.frame
    bounds = sprite.getbbox()
    if not bounds:
        return sprite
    progress = pose.index / max(1,len(species_motion[sid][pose.state])-1)
    character = render_rig(sprite,sid,pose.action_kind,pose.state,progress,
                           facing=1 if pose.direction[0]>=0 else -1)
    if character is not None:
        sx,sy = frame[2]*pose.hit[2]/10000,frame[3]*pose.hit[3]/10000
        scaled = character.resize((max(1,round(character.width*sx)),
                                    max(1,round(character.height*sy))),Image.Resampling.NEAREST)
        angle = -(frame[4]+pose.hit[4]) * (1 if pose.direction[0]>=0 else -1)
        out = scaled.rotate(angle,Image.Resampling.NEAREST,expand=True)
        def point(xy):
            position = (xy[0]*scaled.width/character.width,xy[1]*scaled.height/character.height)
            return tuple(round(v) for v in _point_after_rotation(position,scaled.size,out.size,angle))
        out.info['foot_anchor'] = point(character.info['foot_anchor'])
        out.info['rig_anchors'] = {name:point(xy) for name,xy in character.info['rig_anchors'].items()}
        out.info['rig_parts'] = character.info['rig_parts']
        dissolve = max(frame[5],pose.hit[5])
        if dissolve:
            alpha = out.getchannel('A')
            alpha.putdata([a if (x%2+2*(y%2)) >= dissolve else 0
                           for y in range(out.height) for x in range(out.width)
                           for a in (alpha.getpixel((x,y)),)])
            out.putalpha(alpha)
        return out
    if has_character_rig(sid) and pose.direction[0] >= 0:
        sprite = ImageOps.mirror(sprite)
        bounds = sprite.getbbox()
    cel = sprite.crop(bounds)
    w,h = cel.size
    phase = rig_phase(sid, pose.state, pose.index)
    next_index = 0 if pose.state == 'walk' and math.floor(phase) == len(KEYFRAMES[sid]['walk'])-1 else None
    rigged = rig_cel(cel, sid, phase, next_index)
    if sid == 65 and pose.state in ('idle', 'windup') and math.floor(phase) % 4 in (1, 3):
        # Highlight the existing spoon pixels; do not add an external white blob.
        bright = max((c for c in cel.getdata() if c[3]), key=lambda c: sum(c[:3]))
        draw = ImageDraw.Draw(rigged)
        for left, right in ((0, w//4), (3*w//4, w)):
            candidates = [(x,y) for y in range(h//4, 3*h//4) for x in range(left,right)
                          if rigged.getpixel((x,y))[3]]
            for x,y in candidates[:2]:
                draw.point((x,y), fill=bright)
    sx,sy = frame[2]*pose.hit[2]/10000,frame[3]*pose.hit[3]/10000
    scaled = rigged.resize((max(1,round(w*sx)),max(1,round(h*sy))),Image.Resampling.NEAREST)
    angle = -(frame[4]+pose.hit[4]) * (1 if pose.direction[0]>=0 else -1)
    rotated = scaled.rotate(angle,Image.Resampling.NEAREST,expand=True)
    out = Image.new('RGBA',sprite.size)
    out.paste(rotated,((sprite.width-rotated.width)//2,sprite.height-rotated.height))
    dissolve = max(frame[5],pose.hit[5])
    if dissolve:
        alpha = out.getchannel('A')
        alpha.putdata([a if (x%2+2*(y%2)) >= dissolve else 0
                       for y in range(out.height) for x in range(out.width)
                       for a in (alpha.getpixel((x,y)),)])
        out.putalpha(alpha)
    return out
