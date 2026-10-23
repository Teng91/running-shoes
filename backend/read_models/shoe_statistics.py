"""User-scoped SQL aggregates with bounded recent rows, independent of HTTP/tools."""

from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.models import Run


def shoe_run_statistics(
    db: Session, user_id: int, shoe_ids: list[int], as_of: date, *, include_details: bool = True
) -> dict[int, dict]:
    if not shoe_ids:
        return {}
    scope = (Run.user_id == user_id, Run.shoe_id.in_(shoe_ids))
    end = as_of.isoformat()
    rows = (
        db.query(
            Run.shoe_id,
            func.sum(Run.km),
            func.count(Run.id),
            func.count(func.distinct(Run.date)),
            func.min(Run.date),
            func.max(Run.date),
            func.sum(
                case(
                    (
                        (Run.date >= (as_of - timedelta(days=29)).isoformat()) & (Run.date <= end),
                        Run.km,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        (Run.date >= (as_of - timedelta(days=89)).isoformat()) & (Run.date <= end),
                        Run.km,
                    ),
                    else_=0,
                )
            ),
        )
        .filter(*scope)
        .group_by(Run.shoe_id)
        .all()
    )
    result: dict[int, dict] = {
        shoe_id: {
            "km": 0.0,
            "count": 0,
            "days": 0,
            "first": None,
            "last": None,
            "km_30": 0.0,
            "km_90": 0.0,
            "monthly": {},
            "recent": [],
        }
        for shoe_id in shoe_ids
    }
    for shoe_id, km, count, days, first, last, km_30, km_90 in rows:
        result[shoe_id].update(
            km=km, count=count, days=days, first=first, last=last, km_30=km_30, km_90=km_90
        )

    if not include_details:
        return result

    month_index = as_of.year * 12 + as_of.month - 1
    start_year, start_month = divmod(month_index - 11, 12)
    next_year, next_month = divmod(month_index + 1, 12)
    month = func.substr(Run.date, 1, 7)
    for shoe_id, key, km, count in (
        db.query(Run.shoe_id, month, func.sum(Run.km), func.count(Run.id))
        .filter(
            *scope,
            Run.date >= f"{start_year:04d}-{start_month + 1:02d}-01",
            Run.date < f"{next_year:04d}-{next_month + 1:02d}-01",
        )
        .group_by(Run.shoe_id, month)
        .all()
    ):
        result[shoe_id]["monthly"][key] = {"km": km, "count": count}

    ranked = (
        db.query(
            Run.shoe_id,
            Run.id,
            Run.date,
            Run.km,
            func.row_number()
            .over(partition_by=Run.shoe_id, order_by=(Run.date.desc(), Run.id.desc()))
            .label("position"),
        )
        .filter(*scope)
        .subquery()
    )
    for row in (
        db.query(ranked.c.shoe_id, ranked.c.id, ranked.c.date, ranked.c.km)
        .filter(
            ranked.c.position <= 12,
        )
        .order_by(ranked.c.shoe_id, ranked.c.date.desc(), ranked.c.id.desc())
        .all()
    ):
        result[row.shoe_id]["recent"].append(
            {"id": row.id, "date": row.date, "km": round(float(row.km), 2)}
        )
    return result
