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
            transformed = (grid(at), *ev[1:])
            self._scheduled.append((transformed[0], sequence, transformed))
            self.source_times[sequence] = (ev[0], transformed[0])
            if timing is not None:
                self.action_by_event[id(transformed)] = timing
            sequence += 1
            return transformed

        for index, ev in enumerate(self.source_events):
            t, kind = ev[:2]
            if previous_t is None or abs(t - previous_t) > 1e-8:
                packet = None
            previous_t = t
            if kind == 'deploy':
                positions[ev[2]] = ev[3]
                emit(ev, 0.)
            elif kind in ('attack', 'cast'):
                attacker, target = ev[2:4]
                unit = by_idx[attacker]
                group = cast_groups.get((t, attacker)) if kind == 'attack' else None
                if group is not None:
                    at = max(group.impact, state_ready[attacker], state_ready[target])
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
                    start = grid(max(.4, t, action_ready[attacker], state_ready[attacker],
                                     state_ready[target] - delay))
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
                if not timing.secondary:
                    self.action_by_onset[(attacker, timing.start)] = timing
                emit(ev, timing.start, timing)
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
                state_ready[attacker] = state_ready[target] = timing.impact
                action_ready[attacker] = max(action_ready[attacker], timing.recover_end)
                last_shift[attacker] = last_shift[target] = timing.impact - t
                self.last_impact = max(self.last_impact, timing.impact)
                if kind == 'cast':
                    cast_groups[(t, attacker)] = timing
                    if len(self.cutin_windows) < MAX_CUTINS and (
                            not self.cutin_windows or timing.release >= self.cutin_windows[-1][1] + 2.):
                        self.cutin_windows.append((timing.release, timing.release + CUTIN_DURATION, index))
            elif kind == 'move':
                idx = ev[2]
                if (t,idx) in blink_candidates:
                    pending_blinks[idx] = (ev, positions[idx])
                    positions[idx] = ev[3]
                    continue
                at = grid(max(t, state_ready[idx], action_ready[idx]))
                positions[idx] = ev[3]
                emit(ev, at)
                state_ready[idx] = action_ready[idx] = at + MOVE_DURATION
                last_shift[idx] = at - t
                packet = None
            elif kind in ('unit_state', 'status', 'regen', 'sash', 'die'):
                idx = ev[2]
                belongs = packet is not None and idx in (packet.attacker, packet.target)
                at = packet.impact if belongs else max(t + last_shift[idx], state_ready[idx])
                if kind == 'die':
                    at += HIT_HOLD
                    action_ready[idx] = max(action_ready[idx], at + DEATH_DURATION)
                emit(ev, at)
                state_ready[idx] = max(state_ready[idx], at)
            elif kind == 'end':
                at = max(t, max(action_ready.values(), default=0.),
                         max(state_ready.values(), default=0.))
                self.result_time = grid(at)
                emit(ev, at)
            else:
                emit(ev, max(t, self.last_impact if kind == 'miss' else t))
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
