"""SPEC-023 application use cases and additive nickname storage."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend import credentials, models, schemas
from backend.migrations import run_startup_migrations, schema_version
from backend.services import accounts, goals, shoes
from backend.services.errors import CapacityExceeded, Conflict, Invalid, NotFound, Unauthorized
from backend.services.exports import build_account_export


def test_account_services_enforce_capacity_credentials_and_revocation(db):
    user = accounts.register(db, "  service-user ", "first-pass", max_users=1)
    assert user.username == "service-user"
    with pytest.raises(CapacityExceeded):
        accounts.register(db, "second-user", "second-pass", max_users=1)
    with pytest.raises(Invalid):
        accounts.register(db, "service-user", "second-pass", max_users=1)
    with pytest.raises(Unauthorized):
        accounts.login(db, user.username, "wrong", secret_key="synthetic-service-key" * 2)
    token = accounts.login(db, user.username, "first-pass", secret_key="synthetic-service-key" * 2)
    claims = credentials.decode_access_token(token["access_token"], secret_key="synthetic-service-key" * 2)
    accounts.change_password(db, user.username, "first-pass", "second-pass")
    db.refresh(user)
    assert user.token_version == claims["token_version"] + 1
    assert credentials.verify_password("second-pass", user.hashed_password)
    with pytest.raises(Unauthorized):
        accounts.change_password(db, user.username, "first-pass", "third-pass")


def test_goal_service_is_user_scoped_rejects_stale_versions_and_rolls_back(db, monkeypatch):
    first = models.User(username="goal-first", hashed_password="synthetic")
    second = models.User(username="goal-second", hashed_password="synthetic")
    db.add_all([first, second])
    db.commit()
    initial = goals.update_goal(db, first.id, schemas.RunningGoalUpdate(start_year=2026, monthly_km=100))
    goals.update_goal(db, second.id, schemas.RunningGoalUpdate(start_year=2026, monthly_km=180))
    with pytest.raises(Conflict):
        goals.update_goal(db, first.id, schemas.RunningGoalUpdate(
            start_year=2026, monthly_km=300, expected_version=initial['version'] - 1))
    assert db.query(models.RunningGoal).filter_by(user_id=first.id).one().monthly_km == 100
    assert db.query(models.RunningGoal).filter_by(user_id=second.id).one().monthly_km == 180
    with monkeypatch.context() as patch:
        patch.setattr(db, 'commit', lambda: (_ for _ in ()).throw(RuntimeError('synthetic commit failure')))
        with pytest.raises(RuntimeError):
            goals.update_goal(db, first.id, schemas.RunningGoalUpdate(
                start_year=2026, monthly_km=200, expected_version=initial['version']))
    assert db.query(models.RunningGoal).filter_by(user_id=first.id).one().monthly_km == 100


def test_nickname_persists_is_scoped_and_survives_account_and_safe_csv_exports(db):
    from backend.exporting import generate_shoe_rows
    user = models.User(username='nickname-owner', hashed_password='synthetic')
    other = models.User(username='nickname-other', hashed_password='synthetic')
    db.add_all([user, other])
    db.commit()
    shoe = shoes.create_shoe(db, user.id, schemas.ShoeCreate(
        brand='Same', model='Model', date='2026-01-01', nickname='=synthetic'), max_shoes=5)
    assert schemas.ShoeOut.model_validate(shoe).nickname == '=synthetic'
    assert next(iter(generate_shoe_rows([shoe])))['暱稱'] == "'=synthetic"
    backup, _ = build_account_export(db, user)
    other_backup, _ = build_account_export(db, other)
    assert backup['shoes'][0]['nickname'] == '=synthetic'
    assert other_backup['shoes'] == []
    updated = shoes.update_shoe(db, user.id, shoe.id, schemas.ShoeUpdate(
        nickname='Morning pair', expected_version=shoe.version))
    assert updated.nickname == 'Morning pair'
    with pytest.raises(NotFound):
        shoes.update_shoe(db, other.id, shoe.id, schemas.ShoeUpdate(nickname='Not mine'))
    for payload in [{'nickname': None}, {'nickname': 'x' * 81}]:
        with pytest.raises(ValueError):
            schemas.ShoeUpdate(**payload)


def test_schema_three_nickname_upgrade_preserves_ids_mileage_versions_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schema-two.sqlite'}")
    run_startup_migrations(engine, sessionmaker(bind=engine))
    with Session(engine) as db:
        db.add(models.User(id=1, username='synthetic', hashed_password='synthetic'))
        db.commit()
        db.add(models.Shoe(id=7, user_id=1, brand='A', model='B', date='2026-01-01',
                           mileage=123.45, baseline_mileage=123.45, version=9, categories=[]))
        db.commit()
    with engine.begin() as connection:
        for action in ('insert', 'update', 'delete'):
            connection.execute(text(f'DROP TRIGGER IF EXISTS audit_shoes_{action}'))
        connection.execute(text('ALTER TABLE shoes DROP COLUMN nickname'))
        connection.execute(text("UPDATE schema_metadata SET value='2' WHERE key='schema_version'"))
    run_startup_migrations(engine, sessionmaker(bind=engine))
    assert schema_version(engine) == 11
    with Session(engine) as db:
        shoe = db.get(models.Shoe, 7)
        assert (shoe.nickname, shoe.mileage, shoe.baseline_mileage, shoe.version) == ('', 123.45, 123.45, 9)
        shoe.nickname = 'survives restart'
        db.commit()
    run_startup_migrations(engine, sessionmaker(bind=engine))
    with Session(engine) as db:
        assert db.get(models.Shoe, 7).nickname == 'survives restart'
    engine.dispose()
