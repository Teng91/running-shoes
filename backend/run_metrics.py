"""Canonical run duration and pace arithmetic (SPEC-060).

A run stores its moving time in whole seconds; pace is always derived from
duration and distance here, never stored and never computed by the LLM.
Average pace is time-weighted (total seconds / total km of timed runs), not
a mean of per-run paces.

Activity types (SPEC-096, SPEC-097): every type counts toward shoe mileage;
only training types count toward monthly volume, goals, streaks and weekly
load; only pace types feed pace trends and race readiness. Hikes and walks
are shoe-only. Mirrored in frontend/app-state.js.
"""

ACTIVITY_TYPES = ("road", "trail", "hike", "walk")
DEFAULT_ACTIVITY_TYPE = "road"
TRAINING_ACTIVITY_TYPES = ("road", "trail")
PACE_ACTIVITY_TYPES = ("road",)


def counts_toward_training(activity_type: str | None) -> bool:
    """Whether a run's distance belongs in monthly volume, goals and streaks."""
    return (activity_type or DEFAULT_ACTIVITY_TYPE) in TRAINING_ACTIVITY_TYPES


MAX_RUN_DURATION_SECONDS = 7 * 24 * 60 * 60
# Plausible running pace, in seconds per km: faster than 1:00/km or slower
# than 60:00/km is almost certainly a typo (minutes entered as seconds) or GPS noise.
MIN_PACE_SECONDS_PER_KM = 60
MAX_PACE_SECONDS_PER_KM = 3600
# SPEC-139: hikes and walks climb and stop, so a steep hike slower than 60:00/km is
# real; they accept up to 120:00/km. Mirrored in frontend/app-state.js.
MAX_SHOE_ONLY_PACE_SECONDS_PER_KM = 7200


def max_pace_seconds_per_km(activity_type: str | None = None) -> int:
    """Slowest plausible pace for the activity type; an unknown type is held to running pace."""
    if (activity_type or DEFAULT_ACTIVITY_TYPE) in ACTIVITY_TYPES and not counts_toward_training(activity_type):
        return MAX_SHOE_ONLY_PACE_SECONDS_PER_KM
    return MAX_PACE_SECONDS_PER_KM


def pace_range_text(activity_type: str | None = None) -> str:
    """The accepted pace range for user-facing messages, e.g. 每公里 1:00–60:00."""
    return f"每公里 {MIN_PACE_SECONDS_PER_KM // 60}:00–{max_pace_seconds_per_km(activity_type) // 60}:00"


def pace_seconds_per_km(duration_seconds: float | None, km: float | None) -> int | None:
    """Whole seconds per km, or None when the run has no usable duration or distance."""
    if duration_seconds is None or km is None or duration_seconds <= 0 or km <= 0:
        return None
    return round(duration_seconds / km)


def is_plausible_duration(duration_seconds: float, km: float, activity_type: str | None = None) -> bool:
    """Whether the duration is in range and gives a plausible pace for the distance and type."""
    if not 1 <= duration_seconds <= MAX_RUN_DURATION_SECONDS or km <= 0:
        return False
    return MIN_PACE_SECONDS_PER_KM <= duration_seconds / km <= max_pace_seconds_per_km(activity_type)
