"""Report interleavings use independent connections and an isolated SQLite file."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.migrations import run_startup_migrations, schema_version
from backend.models import MonthlyReport, ReportGeneration, User
from backend.services import reports
from backend.services.report_storage import begin_generation, persist_current_report


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reports.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1, username="one", hashed_password="mock"),
                    User(id=2, username="two", hashed_password="mock")])
        db.commit()
    yield factory
    engine.dispose()


def generate(db, content, *, user=1, month=6, stream=None):
    return reports.generate_report(
        db, user, 2026, month, "mock-model", build_stats=lambda: {"snapshot": content},
        stream_text=stream or (lambda _: iter([content])),
    )


@pytest.mark.parametrize("newer_finishes_first", [True, False])
def test_latest_generation_owns_report_content_and_stats(sessions, newer_finishes_first):
    with sessions() as old_db, sessions() as new_db:
        older, newer = generate(old_db, "older"), generate(new_db, "newer")
        assert next(older) == {"type": "token", "text": "older"}
        assert not old_db.in_transaction(), "LLM wait must not retain a transaction"
        assert next(newer)["type"] == "token"
        if newer_finishes_first:
            assert list(newer)[-1]["type"] == "done"
            assert list(older)[-1]["type"] == "error"
        else:
            assert list(older)[-1]["type"] == "error"
            assert list(newer)[-1]["type"] == "done"
    with sessions() as db:
        row = db.query(MonthlyReport).one()
        assert row.content_md == "newer" and row.stats_json == {"snapshot": "newer"}
        assert db.query(ReportGeneration).count() == 1


@pytest.mark.parametrize("failure", ["empty", "model", "unexpected", "cancel"])
def test_failed_new_generation_preserves_saved_report_and_supersedes_old(sessions, failure):
    def fail(_):
        if failure == "model":
            raise reports.ReportModelError("safe model error")
        if failure == "unexpected":
            raise RuntimeError("private internals")
        return iter([] if failure == "empty" else ["cancelled"])

    with sessions() as db:
        assert list(generate(db, "saved"))[-1]["type"] == "done"
    with sessions() as old_db, sessions() as new_db:
        old = generate(old_db, "old pending")
        next(old)
        new = generate(new_db, "not saved", stream=fail)
        if failure == "cancel":
            next(new)
            new.close()
        else:
            events = list(new)
            assert events[-1]["type"] == "error"
            assert "private internals" not in str(events)
        assert list(old)[-1]["type"] == "error"
    with sessions() as db:
        assert db.query(MonthlyReport).one().content_md == "saved"


def test_generation_scope_and_independent_writers(sessions):
    def reserve():
        with sessions() as db:
            return begin_generation(db, 1, 2026, 6)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: reserve(), range(2)))
    with sessions() as db:
        current = db.query(ReportGeneration).one().token
        stale = next(token for token in tokens if token != current)
        assert persist_current_report(db, 1, 2026, 6, stale, "old", "mock", {}) is None
        assert persist_current_report(db, 2, 2026, 6, current, "stolen", "mock", {}) is None
        assert persist_current_report(db, 1, 2026, 7, current, "wrong month", "mock", {}) is None
        assert persist_current_report(db, 1, 2026, 6, current, "current", "mock", {})
        assert list(generate(db, "other user", user=2))[-1]["type"] == "done"
        assert list(generate(db, "other month", month=7))[-1]["type"] == "done"
        assert db.query(MonthlyReport).count() == 3


def test_report_generation_preparation_and_storage_errors_are_safe(sessions, monkeypatch):
    def broken(*args):
        raise RuntimeError("private internals")

    with sessions() as db:
        monkeypatch.setattr(reports, "begin_generation", broken)
        events = list(generate(db, "test"))
        assert events[-1]["type"] == "error" and not db.in_transaction()
        monkeypatch.setattr(reports, "begin_generation", begin_generation)
        monkeypatch.setattr(reports, "persist_current_report", broken)
        events += list(generate(db, "test"))
        assert events[-1]["type"] == "error" and not db.in_transaction()
        assert "private internals" not in str(events)
        assert db.query(MonthlyReport).count() == 0


def test_statistics_failure_keeps_saved_report_and_supersedes_old(sessions):
    def broken():
        raise RuntimeError("private statistics error")

    with sessions() as db:
        list(generate(db, "saved"))
    with sessions() as old_db, sessions() as new_db:
        old = generate(old_db, "old pending")
        next(old)
        events = list(reports.generate_report(
            new_db, 1, 2026, 6, "mock", build_stats=broken, stream_text=lambda _: iter([])
        ))
        assert events[-1]["type"] == "error" and "private" not in str(events)
        assert list(old)[-1]["type"] == "error"
    with sessions() as db:
        assert db.query(MonthlyReport).one().content_md == "saved"


def test_failed_report_commit_rolls_back_content_and_statistics(sessions, monkeypatch):
    with sessions() as db:
        list(generate(db, "saved"))
        pending = generate(db, "new")
        next(pending)

        def failed_commit():
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(db, "commit", failed_commit)
        assert list(pending)[-1]["type"] == "error"
        assert not db.in_transaction()
    with sessions() as db:
        row = db.query(MonthlyReport).one()
        assert row.content_md == "saved" and row.stats_json == {"snapshot": "saved"}


def test_schema_four_upgrade_preserves_existing_reports(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine, tables=[
        table for table in Base.metadata.sorted_tables if table.name != "report_generations"
    ])
    with factory() as db:
        db.add(User(id=1, username="migration", hashed_password="mock"))
        db.commit()
        db.add(MonthlyReport(user_id=1, year=2026, month=6, content_md="saved", stats_json={"km": 5}))
        db.commit()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT)"))
        connection.execute(text("INSERT INTO schema_metadata VALUES ('schema_version', '3')"))
    for _ in range(2):
        run_startup_migrations(engine, factory)
    assert schema_version(engine) == 15
    assert "report_generations" in inspect(engine).get_table_names()
    with factory() as db:
        row = db.query(MonthlyReport).one()
        assert row.content_md == "saved" and row.stats_json == {"km": 5}
        token = begin_generation(db, 1, 2026, 6)
        assert persist_current_report(db, 1, 2026, 6, token, "new", "mock", {"km": 8})
    engine.dispose()


def test_unexpected_report_failures_reach_the_server_log_not_the_user(sessions, monkeypatch, caplog):
    """SPEC-140: each neutral error has a logged cause; the report text is never logged."""
    def broken(*args):
        raise RuntimeError("private internals")

    def failing_stream(_):
        raise RuntimeError("private stream")

    caplog.set_level("ERROR", logger="running_shoes.reports")
    with sessions() as db:
        monkeypatch.setattr(reports, "begin_generation", broken)
        assert list(generate(db, "test"))[-1]["type"] == "error"
        monkeypatch.setattr(reports, "begin_generation", begin_generation)
        assert list(generate(db, "test", stream=failing_stream))[-1]["type"] == "error"
        monkeypatch.setattr(reports, "persist_current_report", broken)
        events = list(generate(db, "secret report body"))
    assert events[-1]["type"] == "error" and "private" not in str(events)
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["Report preparation failed for 2026-06", "Report model stream failed for 2026-06",
                        "Report save failed for 2026-06"]
    assert all(record.exc_info for record in caplog.records)
    assert "secret report body" not in caplog.text


def test_safe_model_errors_are_not_logged_as_failures(sessions, caplog):
    def refused(_):
        raise reports.ReportModelError("safe model error")

    caplog.set_level("ERROR", logger="running_shoes.reports")
    with sessions() as db:
        assert list(generate(db, "test", stream=refused))[-1] == {"type": "error", "text": "safe model error"}
    assert caplog.records == []
