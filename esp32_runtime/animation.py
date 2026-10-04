"""Portable 2D keyframe contract; no game data, image library or mutable clock.

Rows contain normalized time, dx, dy, angle, scale_x, scale_y, visibility.
The reference sampler rounds to integer pixels with Python ties-to-even. A C
port must match that rule; this module is not an ESP32 drawing backend.
"""
import math

TRACK_FIELDS = ('at', 'dx', 'dy', 'angle', 'scale_x', 'scale_y', 'visible')
MAX_TRACK_KEYS = 16


def validate_track(keys, *, path='track'):
    """Validate authoring data before publishing/caching, never per pixel."""
    if not isinstance(keys, (list, tuple)) or not 2 <= len(keys) <= MAX_TRACK_KEYS:
        raise ValueError(f'{path}: expected 2–{MAX_TRACK_KEYS} keys')
    previous = -1
    for key in keys:
        if not isinstance(key, (list, tuple)) or len(key) != len(TRACK_FIELDS):
            raise ValueError(f'{path}: invalid keyframe fields')
        at, *pose = key
        if type(at) not in (float, int) or not 0 <= at <= 1 or not math.isfinite(at) or at <= previous:
            raise ValueError(f'{path}: key times must increase strictly within 0–1')
        previous = at
        if any(type(value) is not int for value in pose):
            raise ValueError(f'{path}: pose values must be integers')
        dx, dy, angle, sx, sy, visible = pose
        if not (-48 <= dx <= 48 and -48 <= dy <= 48 and -180 <= angle <= 180
                and 50 <= sx <= 150 and 50 <= sy <= 150 and visible in (0, 1)):
            raise ValueError(f'{path}: pose exceeds translation/rotation/scale/visibility limits')
    if keys[0][0] != 0 or keys[-1][0] != 1:
        raise ValueError(f'{path}: track must include endpoints 0 and 1')
    return True


def sample_track(keys, progress):
    """Sample a validated track. Seek order cannot affect the result.

    Continuous dimensions interpolate; visibility changes only at its key.
    Callers validate tracks once at the content boundary.
    """
    if type(progress) not in (int, float) or (type(progress) is float and not math.isfinite(progress)):
        raise ValueError('track progress must be finite')
    if progress <= keys[0][0]:
        return tuple(keys[0][1:])
    if progress >= keys[-1][0]:
        return tuple(keys[-1][1:])
    for left, right in zip(keys, keys[1:]):
        if left[0] <= progress < right[0]:
            mix = (progress-left[0]) / (right[0]-left[0])
            return tuple(round(a+(b-a)*mix) for a, b in zip(left[1:-1], right[1:-1])) + (left[-1],)
    raise ValueError('invalid unvalidated track')
