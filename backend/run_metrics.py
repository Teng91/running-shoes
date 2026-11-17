"""Canonical run duration and pace arithmetic (SPEC-060).

A run stores its moving time in whole seconds; pace is always derived from
duration and distance here, never stored and never computed by the LLM.
Average pace is time-weighted (total seconds / total km of timed runs), not
a mean of per-run paces.
"""

MAX_RUN_DURATION_SECONDS = 7 * 24 * 60 * 60
# Plausible running pace, in seconds per km: faster than 1:00/km or slower
# than 60:00/km is almost certainly a typo (minutes entered as seconds) or GPS noise.
MIN_PACE_SECONDS_PER_KM = 60
MAX_PACE_SECONDS_PER_KM = 3600


def pace_seconds_per_km(duration_seconds: float | None, km: float | None) -> int | None:
    """Whole seconds per km, or None when the run has no usable duration or distance."""
    if duration_seconds is None or km is None or duration_seconds <= 0 or km <= 0:
        return None
    return round(duration_seconds / km)


def is_plausible_duration(duration_seconds: float, km: float) -> bool:
    """Whether the duration is in range and gives a plausible running pace for the distance."""
    if not 1 <= duration_seconds <= MAX_RUN_DURATION_SECONDS or km <= 0:
        return False
    return MIN_PACE_SECONDS_PER_KM <= duration_seconds / km <= MAX_PACE_SECONDS_PER_KM
