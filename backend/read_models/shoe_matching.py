"""Deterministic identity resolution. Ambiguous names must never pick a row."""

from backend import models


def resolve_shoe(
    shoes: list[models.Shoe], name: str = "", shoe_id: int | None = None
) -> tuple[models.Shoe | None, dict | None]:
    if shoe_id is not None:
        selected = next((shoe for shoe in shoes if shoe.id == shoe_id), None)
        return (selected, None) if selected else (None, {"ok": False, "error": "shoe_not_found"})
    query = name.strip().casefold()
    if not query:
        return None, {"ok": False, "error": "shoe_not_found"}
    exact = [shoe for shoe in shoes if f"{shoe.brand} {shoe.model}".casefold() == query]
    candidates = exact or [
        shoe for shoe in shoes if query in f"{shoe.brand} {shoe.model}".casefold()
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, {"ok": False, "error": "shoe_not_found", "query": name}
    return None, {
        "ok": False,
        "error": "ambiguous_shoe",
        "message": "找到多雙鞋款，請使用候選 shoe_id 或詢問使用者，不可猜測。",
        "candidates": [
            {
                "shoe_id": shoe.id,
                "brand": shoe.brand,
                "model": shoe.model,
                "purchase_date": shoe.date,
                "status": "retired" if shoe.is_retired else "active",
            }
            for shoe in sorted(candidates, key=lambda shoe: shoe.id)
        ],
    }
