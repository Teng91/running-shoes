"""SPEC-136: personal bests over 5K, 10K, 15K and the half marathon."""

from datetime import date

from backend.models import Run, Shoe, User
from backend.read_models.personal_bests import personal_bests
from unit_tests.test_run_pace import client, headers

__all__ = ["client"]


def _owner(db, name, nickname=""):
    user = User(username=name, hashed_password="synthetic")
    db.add(user)
    db.flush()
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Sky", nickname=nickname, date="2025-01-01")
    db.add(shoe)
    db.flush()
    return user, shoe


def _runs(db, user, shoe, *rows):
    db.add_all(Run(user_id=user.id, shoe_id=shoe.id, date=day, km=km, duration_seconds=seconds,
                   activity_type=kind)
               for day, km, seconds, kind in rows)
    db.commit()


def _bests(result, key):
    return next(item for item in result["distances"] if item["key"] == key)["bests"]


def test_a_longer_run_holds_a_shorter_best_at_its_average_pace(db):
    user, shoe = _owner(db, "pb-longer", nickname="比賽鞋")
    _runs(db, user, shoe,
          # A half at 4:40/km beats every 5K and 10K run below, so it holds both bests.
          ("2026-03-01", 21.0975, 5907, "road"),
          ("2026-04-01", 5.0, 1500, "road"),       # 5:00/km
          ("2026-04-02", 10.0, 2900, "road"),      # 4:50/km
          ("2026-04-03", 4.97, 1342, "road"),      # GPS a little short: still a 5K, 4:30/km
          ("2026-04-04", 4.9, 1100, "road"),       # too short for a 5K
          ("2026-04-05", 16.0, 4400, "road"))      # 4:35/km over 16 km
    result = personal_bests(db, user.id, date(2026, 6, 1))
    assert [item["key"] for item in result["distances"]] == ["5k", "10k", "15k", "half"]
    assert result["top_count"] == 3

    five = _bests(result, "5k")
    assert [(row["rank"], row["seconds"], row["date"]) for row in five] == [
        (1, 1350, "2026-04-03"), (2, 1375, "2026-04-05"), (3, 1400, "2026-03-01")]
    assert five[0] == {"rank": 1, "seconds": 1350, "pace": 270, "date": "2026-04-03", "run_km": 4.97,
                       "from_longer_run": False, "shoe": "Mizuno Sky（比賽鞋）"}
    assert five[2]["from_longer_run"] is True and five[2]["run_km"] == 21.1

    # 16 km at 4:35 beats the half at 4:40 over 10K and 15K; the 10 km run at 4:50 is third.
    assert [(row["seconds"], row["date"]) for row in _bests(result, "10k")] == [
        (2750, "2026-04-05"), (2800, "2026-03-01"), (2900, "2026-04-02")]
    assert [(row["seconds"], row["pace"]) for row in _bests(result, "15k")] == [(4125, 275), (4200, 280)]
    assert [(row["seconds"], row["pace"], row["from_longer_run"]) for row in _bests(result, "half")] == [
        (5907, 280, False)]


def test_only_timed_past_road_runs_of_this_account_count(db, client):
    user, shoe = _owner(db, "pb-scope")
    other, other_shoe = _owner(db, "pb-scope-other")
    _runs(db, user, shoe,
          ("2026-05-01", 5.0, 1500, "road"),
          ("2026-05-02", 5.0, None, "road"),        # untimed
          ("2026-05-03", 5.0, 1000, "trail"),       # trail pace is not comparable
          ("2026-05-04", 5.0, 900, "walk"),
          ("2026-07-01", 5.0, 1200, "road"))        # after today
    _runs(db, other, other_shoe, ("2026-05-01", 5.0, 1100, "road"))
    result = personal_bests(db, user.id, date(2026, 6, 1))
    assert [(row["seconds"], row["date"]) for row in _bests(result, "5k")] == [(1500, "2026-05-01")]
    assert all(not _bests(result, key) for key in ("10k", "15k", "half"))

    response = client.get("/api/analytics/personal-bests", headers=headers(user))
    assert response.status_code == 200
    assert [item["label"] for item in response.json()["distances"]] == ["5K", "10K", "15K", "半馬"]
    assert client.get("/api/analytics/personal-bests").status_code == 401


def test_a_tie_goes_to_the_run_that_set_it_first_and_only_three_are_kept(db):
    user, shoe = _owner(db, "pb-ties")
    _runs(db, user, shoe,
          ("2026-02-01", 5.0, 1500, "road"),
          ("2026-01-01", 5.0, 1500, "road"),
          ("2026-03-01", 5.0, 1490, "road"),
          ("2026-04-01", 5.0, 1600, "road"))
    five = _bests(personal_bests(db, user.id, date(2026, 6, 1)), "5k")
    assert [(row["rank"], row["seconds"], row["date"]) for row in five] == [
        (1, 1490, "2026-03-01"), (2, 1500, "2026-01-01"), (3, 1500, "2026-02-01")]
