"""Three physical keys: monotonic press/release gestures, independent of pages.

Hosts send down/up/tick/cancel; they never send a synthesized click or duration.
The first held key owns the gesture. Wake, blocked presses and chords are drained
through release; cancellation never creates an action. This is a host reference,
not a claim that an ESP32 driver or GPIO debounce implementation exists.
"""
import math
import time

KEYS = ("A", "B", "C")
LONG_SECONDS = .600
SLEEP_SECONDS = 1.500
IDLE_SECONDS = 60.0
TRANSITION_SECONDS = .100


class GestureInput:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.held = {}
        self.sleeping = False
        self.blocked_until = -1.0
        self.last_activity = clock()
        self.last_time = -1.0

    def block(self, now=None):
        now = self.clock() if now is None else now
        self.blocked_until = max(self.blocked_until, now + TRANSITION_SECONDS)

    def _long(self, now):
        events = []
        for key, hold in self.held.items():
            if hold["swallow"]:
                continue
            age = now - hold["start"]
            if key == "C" and age + 1e-9 >= SLEEP_SECONDS and not hold["sleep"]:
                hold["long"] = hold["sleep"] = True
                self.sleeping = True
                events.append(("sleep", key))
                for item in self.held.values():
                    item["swallow"] = True
            elif key in ("B", "C") and age + 1e-9 >= LONG_SECONDS and not hold["long"]:
                hold["long"] = True
                events.append(("back" if key == "B" else "detail", key))
        return events

    def feed(self, phase, key=None, *, now=None, busy=False):
        if phase not in ("down", "up", "tick", "cancel", "state"):
            raise ValueError("未知输入阶段")
        if phase in ("down", "up") and key not in KEYS:
            raise ValueError("只支持 A / B / C 三个按键")
        now = self.clock() if now is None else now
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now < self.last_time:
            raise ValueError("输入时钟必须单调")
        self.last_time = now
        if phase == "cancel":
            self.held.clear()
            self.last_activity = now
            self.block(now)
            return []
        if phase == "state":
            return []
        if phase == "down":
            if key in self.held:  # OS repeat is neither a new press nor a click.
                return []
            swallow = bool(self.held) or busy or now < self.blocked_until
            waking = self.sleeping and not self.held and not busy
            self.held[key] = {"start": now, "long": False, "sleep": False,
                              "swallow": swallow or waking}
            self.last_activity = now
            if waking:
                self.sleeping = False
                return [("wake", key)]
            return []
        if busy:
            for hold in self.held.values():
                hold["swallow"] = True
        events = self._long(now)
        if phase == "up":
            hold = self.held.pop(key, None)
            if hold and not hold["long"] and not hold["swallow"] and not self.sleeping:
                events.append(("click", key))
            self.last_activity = now
        if phase == "tick" and not self.held and not self.sleeping and not busy \
                and now - self.last_activity >= IDLE_SECONDS:
            self.sleeping = True
            events.append(("sleep", None))
        return events
