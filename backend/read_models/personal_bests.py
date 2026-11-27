"""User-scoped personal bests over 5K, 10K, 15K and the half marathon (SPEC-136).

A run records only its total distance and moving time, so a best over a distance is a run's
average pace held over that distance: every timed road run at least that long counts, its time
scaled to the distance. A 21.1 km run at 5:00/km is a 25:00 5K, so a fast half can hold the 5K
best. The fastest stretch inside a run may have been quicker still; a best never claims more
than the run's own average.
"""

from __future__ import annotations

import heapq
from datetime import date

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import PACE_RUN
from backend.run_metrics import pace_seconds_per_km

# (key, label, km); the order the screen shows them in.
DISTANCES = (
    ("5k", "5K", 5.0),
    ("10k", "10K", 10.0),
    ("15k", "15K", 15.0),
    ("half", "半馬", 21.0975),
)
TOP_COUNT = 3
# GPS often measures a race a little short; a run up to 1% under the distance still counts.
DISTANCE_TOLERANCE = 0.01


def _shoe_name(brand: str, model: str, nickname: str | None) -> str:
    return f"{brand} {model}" + (f"（{nickname}）" if nickname else "")


def _entry(rank: int, seconds: float, distance_km: float, run: tuple) -> dict:
    day, km, _, shoe = run
    return {
        "rank": rank,
        "seconds": round(seconds),
        "pace": pace_seconds_per_km(seconds, distance_km),
        "date": day,
        "run_km": round_metric(km),
        # The best is part of a longer run, held at that run's average pace.
        "from_longer_run": km > distance_km * (1 + DISTANCE_TOLERANCE),
        "shoe": shoe,
    }


def _bests(runs: list[tuple], distance_km: float) -> list[dict]:
    shortest = distance_km * (1 - DISTANCE_TOLERANCE)
    # Fastest first; a tie goes to the run that set it first.
    candidates = ((seconds * distance_km / km, day, index)
                  for index, (day, km, seconds, _) in enumerate(runs) if km >= shortest)
    fastest = heapq.nsmallest(TOP_COUNT, candidates)
    return [_entry(rank, seconds, distance_km, runs[index])
            for rank, (seconds, _, index) in enumerate(fastest, start=1)]


def personal_bests(db: Session, user_id: int, as_of: date) -> dict:
    rows = (
        db.query(models.Run.date, models.Run.km, models.Run.duration_seconds,
                 models.Shoe.brand, models.Shoe.model, models.Shoe.nickname)
        .join(models.Shoe, (models.Shoe.id == models.Run.shoe_id) & (models.Shoe.user_id == user_id))
        # Road runs only: trail climbs and hikes would distort pace (SPEC-096).
        .filter(models.Run.user_id == user_id, PACE_RUN, models.Run.duration_seconds.is_not(None),
                models.Run.km >= DISTANCES[0][2] * (1 - DISTANCE_TOLERANCE),
                models.Run.date <= as_of.isoformat())
        .order_by(models.Run.date, models.Run.id)
        .all()
    )
    runs = [(day, float(km), seconds, _shoe_name(brand, model, nickname))
            for day, km, seconds, brand, model, nickname in rows]
    return {
        "as_of": as_of.isoformat(),
        "top_count": TOP_COUNT,
        "distances": [{"key": key, "label": label, "distance_km": km, "bests": _bests(runs, km)}
                      for key, label, km in DISTANCES],
    }
