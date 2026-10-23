from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models, schemas
from backend.database import configure_sqlite_connection
from backend.migrations import run_startup_migrations
from backend.services import runs, shoes
from backend.settings import settings


@pytest.fixture
def workspace(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'workspace.sqlite'}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    factory = sessionmaker(bind=engine, autoflush=False)
    run_startup_migrations(engine, factory)
    with factory() as db:
        db.add_all([models.User(id=1, username="one", hashed_password="synthetic"),
                    models.User(id=2, username="two", hashed_password="synthetic")])
        db.commit()
    config = replace(settings, seed_data=False, fly_app_name=None, database_dir=tmp_path,
                     database_url=str(engine.url))
    yield SimpleNamespace(engine=engine, sessions=factory, config=config)
    engine.dispose()


def add_shoe(db, uid=1, **values):
    return shoes.create_shoe(db, uid, schemas.ShoeCreate(brand="Test", model="Runner", date="2026-01-01",
                                                       **values), max_shoes=500)


def add_run(db, shoe_id, uid=1, **values):
    return runs.create_run(db, uid, schemas.RunCreate(shoe_id=shoe_id, date="2026-01-02", km=values.get("km", 5)), max_runs=5000)
