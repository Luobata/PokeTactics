"""Deterministic shared weather windows; no RNG, damage, or unit ownership.

Requests are collected by simulation tick and become effective on the next
tick. Call ``advance`` before actions, never between same-tick actions. A
request already made survives its caster's subsequent death.
"""
import math

WEATHER_WINDOW_SECONDS = 8.0  # Prototype parameter, not a balance assertion.


class WeatherController:
    def __init__(self, base_weather, tick_seconds):
        self.base_weather = base_weather
        self.weather_name = base_weather
        self.tick_seconds = tick_seconds
        self.expires_at = None
        self._active_requests = []
        self._pending = {}

    def request(self, t, team, source, source_pos, weather, cast_index):
        if weather not in ("sun", "rain"):
            raise ValueError("tactical weather must be sun or rain")
        tick = int(math.floor((t + 1e-9) / self.tick_seconds))
        row = {"team": team, "source": source, "source_pos": tuple(source_pos),
               "weather": weather, "requested_at": t,
               "cast_index": cast_index,
               "effective_at": round((tick + 1) * self.tick_seconds, 9)}
        self._pending.setdefault(tick, []).append(row)
        return dict(row)

    def _transition(self, kind, t, requests, reason, old_weather,
                    previous_expires_at=None):
        return {"kind": kind, "time": t, "requests": [dict(r) for r in requests],
                "old_weather": old_weather, "new_weather": self.weather_name,
                "base_weather": self.base_weather, "expires_at": self.expires_at,
                "previous_expires_at": previous_expires_at, "reason": reason}

    def _expire(self, t, transitions):
        if self.expires_at is None or self.expires_at > t + 1e-9:
            return
        old_weather, expiry = self.weather_name, self.expires_at
        requests = self._active_requests
        self.weather_name, self.expires_at = self.base_weather, None
        self._active_requests = []
        transitions.append(self._transition("weather_end", expiry, requests,
                                            "expired", old_weather, expiry))

    def advance(self, t):
        """Return authoritative transitions through t, in chronological order.

        Expiry restores the base, never an earlier override. Simultaneous
        conflicting requests also restore the base and consume both requests;
        identical requests share one window and never add durations together.
        """
        transitions = []
        ready = sorted(tick for tick, rows in self._pending.items()
                       if rows[0]["effective_at"] <= t + 1e-9)
        for tick in ready:
            requests = self._pending.pop(tick)
            # Output is stable under caller order; the winner never uses this
            # order, only the set of requested weather values.
            requests.sort(key=lambda r: (r["weather"], r["team"], r["source"]))
            start = requests[0]["effective_at"]
            self._expire(start, transitions)
            old_weather, old_expiry = self.weather_name, self.expires_at
            if len({r["weather"] for r in requests}) > 1:
                self.weather_name, self.expires_at = self.base_weather, None
                self._active_requests = []
                transitions.append(self._transition("weather_conflict", start,
                                                    requests, "conflict", old_weather,
                                                    old_expiry))
                continue
            weather = requests[0]["weather"]
            same_active = old_expiry is not None and old_weather == weather
            self.weather_name = weather
            self.expires_at = max(start + WEATHER_WINDOW_SECONDS,
                                  old_expiry if same_active else 0.0)
            self.expires_at = round(self.expires_at, 9)
            self._active_requests = requests
            reason = "extended" if same_active else ("overridden" if old_expiry is not None
                                                     else "requested")
            transitions.append(self._transition("weather_start", start, requests,
                                                reason, old_weather, old_expiry))
        self._expire(t, transitions)
        return transitions
