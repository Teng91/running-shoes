"""SPEC-020 shared calendar semantics and constant aggregate query budgets."""

from datetime import date

import pytest
from sqlalchemy import event

from backend import goals, models, reports
from backend.read_models.run_statistics import (
    month_bounds,
    period_distances,
    run_period,
    sum_run_distance,
)


@pytest.mark.parametrize(
    ("year", "month", "today", "month_end", "previous_end", "label"),
    [
        (2024, 2, date(2024, 2, 29), "2024-02-29", "2024-01-29", "較上月同期"),
        (2024, 3, date(2024, 3, 31), "2024-03-31", "2024-02-29", "較上月同期"),
        (2026, 1, date(2026, 1, 1), "2026-01-01", "2025-12-01", "較上月同期"),
        (2026, 1, date(2026, 10, 22), "2026-01-31", "2025-12-31", "與上月比較"),
        (2026, 12, date(2026, 10, 22), "2026-11-30", "2026-10-31", "尚未開始"),
    ],
)
def test_shared_period_handles_calendar_boundaries(
    year, month, today, month_end, previous_end, label
):
    period = run_period(year, month, today)
    assert period.month_end == month_end
    assert period.previous_end == previous_end
    assert period.comparison_label == label
    assert month_bounds(2024, 2) == ("2024-02-01", "2024-02-29")


def test_period_aggregate_is_one_query_and_excludes_other_users_and_manual_mileage(
    db, user_with_token
):
    user = user_with_token[0]
    shoe = models.Shoe(user_id=user.id, brand="A", model="B", date="2026-01-01")
    other = models.User(username="stats-other", hashed_password="synthetic")
    db.add_all([shoe, other])
    db.flush()
    other_shoe = models.Shoe(user_id=other.id, brand="Private", model="Private", date="2026-01-01")
    db.add(other_shoe)
    db.flush()
    db.add_all(
        [
            models.Run(user_id=user.id, shoe_id=shoe.id, date="2025-12-01", km=2),
            models.Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-01", km=5),
            models.Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-02", km=99),
            models.Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-01-01", km=999),
            models.MonthlyMileage(user_id=user.id, year=2026, month=1, km=900),
        ]
    )
    db.commit()
    user_id = user.id
    statements = []

    def record(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        assert period_distances(db, user_id, run_period(2026, 1, date(2026, 1, 1))) == {
            "month_km": 5,
            "previous_km": 2,
            "ytd_km": 5,
        }
        assert len(statements) == 1
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert sum_run_distance(db, user_id, "2026-01-01", "2026-01-01") == 5
    assert period_distances(db, user_id, run_period(2027, 1, date(2026, 1, 1))) == {
        "month_km": 0,
        "previous_km": 0,
        "ytd_km": 0,
    }


@pytest.mark.parametrize("month", [1, 12])
def test_report_ytd_uses_one_shared_aggregate_independent_of_month(db, user_with_token, month):
    user_id = user_with_token[0].id
    statements = []

    def record(_connection, _cursor, statement, *_args):
        if "CASE WHEN" in statement and "runs" in statement:
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        stats = reports.build_report_stats(db, user_id, 2025, month, today=date(2026, 10, 22))
        assert stats["ytd_run_km"] == 0
        assert len(statements) == 1
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    progress = goals.goal_progress(db, user_id, 2025, month, as_of=date(2026, 10, 22))
    assert stats["running_goal"] == progress
