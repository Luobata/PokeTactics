"""Pure, bounded battle presentation scheduling. Never mutates simulation events.

Per-unit causal fences preserve the order of authoritative state snapshots while
independent units act concurrently. Damage effects land at an action's impact;
windup, release and travel precede it. No cinematic adds time or queues globally.
All durations are seconds on a 20 Hz presentation grid, independent of playback speed.
"""
from bisect import bisect_right
from dataclasses import dataclass
import math

GRID = .05
MOVE_DURATION = .25
HIT_HOLD = .10
END_HOLD = .80
DEATH_DURATION = .80
MAX_TRAVEL = .45
MAX_ACTIVE_SIGNATURES = 3
MAX_CUTINS = 2
CUTIN_DURATION = .20
CORE_CAST_SPECIES = (6, 9, 3, 26, 65, 94, 76, 143)
CORE_CAST_TRAVEL = .20


def grid(value):
    return round(math.ceil((value - 1e-9) / GRID) * GRID, 6)


def _effect_packets(events):
    """Read explicit cast ownership without inferring it from time or species.

    A skill_effect payload's cast_index points into the raw event list, and its
    event_count owns exactly that many following records. Older replay streams
    without these optional markers retain the legacy packet scheduling path.
    """
    owners, participants = {}, {}
    for index, ev in enumerate(events):
        if ev[1] != 'skill_effect' or len(ev) != 7 or not isinstance(ev[6], dict):
            continue
        cast_index, count = ev[6].get('cast_index'), ev[6].get('event_count')
        if (type(cast_index) is not int or type(count) is not int
                or not 0 <= cast_index < index or count < 1
                or index + count >= len(events)):
            continue
        cast = events[cast_index]
        if cast[1] != 'cast' or cast[2] != ev[2]:
            continue
        affected = participants.setdefault(cast_index, {cast[2], cast[3]})
        owners[index] = cast_index
        for child_index in range(index + 1, index + count + 1):
            child = events[child_index]
            owners[child_index] = cast_index
            if child[1] in ('attack', 'cast'):
                affected.update(child[2:4])
            elif child[1] in ('move', 'unit_state', 'status', 'regen', 'sash', 'die'):
                affected.add(child[2])
    return owners, participants


@dataclass(frozen=True)
class ActionTiming:
    source_index: int
    kind: str
    attacker: int
    target: int
    start: float
    release: float
    impact: float
    recover_end: float
    secondary: bool = False
    source_pos: tuple = (0, 0)
    target_pos: tuple = (0, 0)


class AnimationTimeline:
    """Compile raw tuples into ordered presentation tuples with the same ABI.

    ``events`` remains compatible with the existing event formatter. Attack/cast
    timestamps denote action onset; their following unit_state/status/die records
    are retimed to impact. ``actions`` provides release/impact for visual renderers.
    ``duration`` includes all deaths and the final result hold, with no extra delay
    required from the caller. ``time(seconds, speed, skip)`` is the sole UI clock.
    """
    def __init__(self, events, units, windup=None):
        self.source_events = tuple(events)
        by_idx = {unit.idx: unit for unit in units}
        positions = {unit.idx: unit.pos for unit in units}
        state_ready = {idx: 0.0 for idx in by_idx}
        action_ready = dict(state_ready)
        last_shift = dict(state_ready)
        self.actions = []
        self.action_by_event = {}
        self.action_by_onset = {}
        self.source_times = {}
        self.cutin_windows = []
        self.blinks = []
        self.blink_by_event = {}
        self._scheduled = []
        cast_groups = {}
        effects, cast_participants = _effect_packets(self.source_events)
        guarded_actions, guard_owners = {}, {}
        for index, event in enumerate(self.source_events):
            if len(event) != 6 or event[1] != 'tactical_effect' or event[4] != 'guard':
                continue
            payload = event[5]
            owner = payload.get('result_event_index') if isinstance(payload, dict) else None
            if type(owner) is not int or not index < owner < len(self.source_events):
                continue
            result = self.source_events[owner]
            if result[1] not in ('cast', 'miss') or result[2] != payload.get('attacker_idx'):
                continue
            guarded_actions.setdefault(owner, []).append(event)
            guard_owners[index] = owner
            if result[1] == 'cast':
                affected = cast_participants.setdefault(owner, {result[2], result[3]})
                affected.add(event[3])
                count = payload.get('result_event_count', 0)
                if type(count) is int and 0 <= count < len(self.source_events)-owner:
                    for child_index in range(owner+1, owner+count+1):
                        child = self.source_events[child_index]
                        effects[child_index] = owner
                        if child[1] in ('attack', 'cast'):
                            affected.update(child[2:4])
                        elif child[1] in ('move', 'unit_state', 'status', 'regen', 'sash', 'die'):
                            affected.add(child[2])
        actions_by_source = {}
        weather_ready = 0.
        packet = None
        previous_t = None
        self.last_impact = 0.
        self.result_time = None
        sequence = 0
        opening_combo = any(e[1] == 'combo' and e[0] == 0 for e in self.source_events)
        blink_candidates = {(e[0],e[2]) for e in self.source_events
                            if e[1]=='cast' and by_idx[e[2]].piece.species_id==65}
        pending_blinks = {}

        def emit(ev, at, timing=None):
            nonlocal sequence
            if len(ev) == 6 and ev[1] == 'tactical_effect':
                # Preserve the original clock without mutating the simulation.
                transformed = (grid(at), *ev[1:5], {**ev[5], 'simulation_time': ev[0]})
            else:
                transformed = (grid(at), *ev[1:])
            self._scheduled.append((transformed[0], sequence, transformed))
            self.source_times[sequence] = (ev[0], transformed[0])
            if timing is not None:
                self.action_by_event[id(transformed)] = timing
            sequence += 1
            return transformed

        for index, ev in enumerate(self.source_events):
            t, kind = ev[:2]
            effect_action = actions_by_source.get(effects.get(index))
            if previous_t is None or abs(t - previous_t) > 1e-8:
                packet = None
            previous_t = t
            if index in guard_owners:
                # The simulator gives exact ownership, including a dodge outcome.
                # Schedule the transfer with that hit, not the raw pre-cast time.
                continue
            if kind == 'deploy':
                positions[ev[2]] = ev[3]
                emit(ev, 0.)
            elif kind in ('attack', 'cast'):
                attacker, target = ev[2:4]
                unit = by_idx[attacker]
                group = effect_action if kind == 'attack' else None
                if group is None and kind == 'attack':
                    legacy = cast_groups.get((t, attacker))
                    # Explicit effects have bounded ownership. Another same-tick
                    # action after their range must get its own windup/recovery.
                    if legacy is not None and legacy.source_index not in cast_participants:
                        group = legacy
                if group is not None:
                    at = (group.impact if effect_action is not None else
                          max(group.impact, state_ready[attacker], state_ready[target]))
                    timing = ActionTiming(index, kind, attacker, target, at, at, at, at, True,
                                          positions[attacker], positions[target])
                else:
                    # Deliberate role timing: wings gather then expel, psychic focuses
                    # quickly, the heavy body visibly loads its weight before contact.
                    sid = unit.piece.species_id
                    base_prep = ({6: .30, 65: .25, 143: .45}.get(sid, .25)
                                 if kind == 'attack' else
                                 {6: .50, 65: .45, 143: .60}.get(sid, .40))
                    distance = math.dist(positions[attacker], positions[target]) * 40
                    ranged = unit.range > 1 or (kind == 'cast' and sid in CORE_CAST_SPECIES)
                    travel = grid(min(MAX_TRAVEL, max(.15, distance / 520))) if ranged else .05
                    if kind == 'cast' and sid in CORE_CAST_SPECIES:
                        # At least four native 20 Hz frames expose the material
                        # track even when two bodies occupy adjacent cells.
                        travel = max(CORE_CAST_TRAVEL, travel)
                    delay = base_prep + travel
                    affected = cast_participants.get(index, {attacker, target})
                    state_fence = max(state_ready[idx] for idx in affected)
                    start = grid(max(.4, t, weather_ready, action_ready[attacker], state_ready[attacker],
                                     state_fence - delay))
                    release = grid(start + base_prep)
                    impact = grid(release + travel)
                    if opening_combo and t == 0 and kind == 'attack':
                        # Sim launches both volleys before applying damage. Retain
                        # that launch simultaneity even if raw packet order killed a sender.
                        start, release, impact = .4, grid(.4+base_prep), 1.3
                    recovery = {6: .25, 65: .20, 143: .35}.get(sid, .20)
                    timing = ActionTiming(index, kind, attacker, target, start, release,
                                          impact, grid(impact + recovery), False,
                                          positions[attacker], positions[target])
                self.actions.append(timing)
                actions_by_source[index] = timing
                if not timing.secondary:
                    self.action_by_onset[(attacker, timing.start)] = timing
                emit(ev, timing.start, timing)
                for guard_event in guarded_actions.get(index, ()):
                    emit(guard_event, timing.impact)
                if attacker in pending_blinks and kind == 'cast':
                    movement, origin = pending_blinks.pop(attacker)
                    departure = grid(timing.start+.10)
                    landing = grid(timing.start+.30)
                    blink = {"unit":attacker,"start":timing.start,"departure":departure,
                             "landing":landing,"origin":origin,"target":movement[3]}
                    moved = emit(movement, landing)
                    self.blinks.append(blink)
                    self.blink_by_event[id(moved)] = blink
                packet = timing
                for idx in cast_participants.get(index, {attacker, target}):
                    state_ready[idx] = max(state_ready[idx], timing.impact)
                    last_shift[idx] = timing.impact - t
                action_ready[attacker] = max(action_ready[attacker], timing.recover_end)
                self.last_impact = max(self.last_impact, timing.impact)
                if kind == 'cast':
                    cast_groups[(t, attacker)] = timing
                    if len(self.cutin_windows) < MAX_CUTINS and (
                            not self.cutin_windows or timing.release >= self.cutin_windows[-1][1] + 2.):
                        self.cutin_windows.append((timing.release, timing.release + CUTIN_DURATION, index))
            elif kind == 'move':
                idx = ev[2]
                if effect_action is None and (t,idx) in blink_candidates:
                    pending_blinks[idx] = (ev, positions[idx])
                    positions[idx] = ev[3]
                    continue
                # Forced displacement belongs to the incoming hit, even while
                # the victim is recovering from its own earlier action.
                at = (effect_action.impact if effect_action is not None else
                      grid(max(t, weather_ready, state_ready[idx], action_ready[idx])))
                positions[idx] = ev[3]
                emit(ev, at)
                state_ready[idx] = max(state_ready[idx], at + MOVE_DURATION)
                action_ready[idx] = max(action_ready[idx], at + MOVE_DURATION)
                last_shift[idx] = at - t
                packet = None
            elif kind in ('unit_state', 'status', 'regen', 'sash', 'die'):
                idx = ev[2]
                belongs = packet is not None and idx in (packet.attacker, packet.target)
                at = (effect_action.impact if effect_action is not None else
                      packet.impact if belongs else max(t + last_shift[idx], state_ready[idx]))
                if kind == 'die':
                    at += HIT_HOLD
                    action_ready[idx] = max(action_ready[idx], at + DEATH_DURATION)
                emit(ev, at)
                state_ready[idx] = max(state_ready[idx], at)
            elif kind == 'skill_effect' and effect_action is not None:
                emit(ev, effect_action.impact)
            elif kind == 'tactical_effect' and len(ev) == 6:
                payload, effect = ev[5], ev[4]
                if effect in ('weather_start', 'weather_end', 'weather_conflict'):
                    # Weather is shared state. Finish older damage before changing
                    # the scene, and start subsequent attacks after this boundary.
                    at = max(t, weather_ready, max(state_ready.values(), default=0.))
                    weather_ready = grid(at)
                    emit(ev, at)
                elif effect == 'weather_request':
                    owner = actions_by_source.get(payload.get('cast_index'))
                    emit(ev, owner.impact if owner is not None else max(t, weather_ready))
                else:
                    emit(ev, max(t, weather_ready, state_ready.get(ev[2], 0.),
                                 state_ready.get(ev[3], 0.)))
            elif kind == 'end':
                at = max(t, weather_ready, max(action_ready.values(), default=0.),
                         max(state_ready.values(), default=0.))
                self.result_time = grid(at)
                emit(ev, at)
            else:
                at = max(t, weather_ready, self.last_impact if kind == 'miss' else t)
                for guard_event in guarded_actions.get(index, ()):
                    emit(guard_event, at)
                emit(ev, at)
        self.events = [entry[2] for entry in sorted(self._scheduled)]
        # Public logs describe landed damage. The internal rendering stream starts
        # attack choreography earlier, without displaying health changes early.
        self.public_events = sorted((
            (self.action_by_event[id(ev)].impact, *ev[1:]) if id(ev) in self.action_by_event else ev
            for ev in self.events), key=lambda ev: ev[0])
        self.event_times = [ev[0] for ev in self.events]
        self.duration = grid(max(self.event_times, default=0.) + END_HOLD)
        del self._scheduled

    def time(self, seconds, speed=1., skip=False):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('speed must be finite and positive')
        if not math.isfinite(seconds):
            raise ValueError('playback time must be finite')
        return self.duration if skip else min(self.duration, max(0., seconds * speed))

    def recent_events(self, t, lookback=2.):
        left = bisect_right(self.event_times, t - lookback)
        right = bisect_right(self.event_times, t + 1e-9)
        return self.events[left:right]
