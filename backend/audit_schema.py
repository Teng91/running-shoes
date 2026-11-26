"""SQLite audit triggers cover ORM, bulk SQL and mileage side effects atomically."""

from sqlalchemy.engine import Engine

from backend import models

AUDITED = {"shoes": models.Shoe, "runs": models.Run,
           "monthly_mileages": models.MonthlyMileage, "running_goals": models.RunningGoal,
           # SPEC-128: the target race shows in the history and a deleted one can be recovered.
           "race_goals": models.RaceGoal}
# Entities whose events a v6 account archive carries; race goal events stay out of backups.
ARCHIVED_HISTORY_ENTITIES = ("shoes", "runs", "monthly_mileages", "running_goals")


def install_audit_triggers(engine: Engine) -> None:
    """(Re)build every trigger from current model metadata in one transaction.

    Triggers embed the audited column list. Rebuilding on every startup keeps
    snapshots complete after a column is added and avoids a trigger that still
    references a dropped or renamed column and would fail every write.
    """
    with engine.begin() as connection:
        for table, model in AUDITED.items():
            for action in ("INSERT", "UPDATE", "DELETE"):
                alias = "OLD" if action == "DELETE" else "NEW"
                snapshots = []
                for prefix in ("OLD", "NEW"):
                    if (prefix == "OLD" and action == "INSERT") or (prefix == "NEW" and action == "DELETE"):
                        snapshots.append("NULL")
                    else:
                        fields = ", ".join(
                            f"'{column.name}', {prefix}.{column.name}"
                            for column in model.__table__.columns if column.name != "user_id"
                        )
                        snapshots.append(f"json_object({fields})")
                # Identifiers come exclusively from model metadata, never input.
                sequence = (
                    f"INSERT INTO entity_sequences(name,next_id) VALUES ('{table}',OLD.id+1) "
                    "ON CONFLICT(name) DO UPDATE SET next_id=max(next_id,excluded.next_id);"
                    if action == "DELETE" and table in {"runs", "monthly_mileages"} else ""
                )
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS audit_{table}_{action.lower()}")
                connection.exec_driver_sql(f"""
                    CREATE TRIGGER audit_{table}_{action.lower()}
                    AFTER {action} ON {table} BEGIN
                      {sequence}
                      UPDATE users SET data_revision = data_revision + 1 WHERE id = {alias}.user_id;
                      INSERT INTO audit_events
                        (user_id,operation_id,reason,entity,entity_id,action,before_json,after_json,created_at,restored,imported)
                      VALUES ({alias}.user_id,
                        COALESCE((SELECT operation_id FROM write_contexts WHERE user_id={alias}.user_id), lower(hex(randomblob(16)))),
                        COALESCE((SELECT reason FROM write_contexts WHERE user_id={alias}.user_id), 'legacy.write'),
                        '{table}', {alias}.id, '{action.lower()}', {snapshots[0]}, {snapshots[1]},
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'), 0, 0);
                    END
                """)
        for table in ("monthly_reports", "strava_imports"):
            for action in ("INSERT", "UPDATE", "DELETE"):
                alias = "OLD" if action == "DELETE" else "NEW"
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS revision_{table}_{action.lower()}")
                connection.exec_driver_sql(f"""
                    CREATE TRIGGER revision_{table}_{action.lower()}
                    AFTER {action} ON {table} BEGIN
                      UPDATE users SET data_revision = data_revision + 1 WHERE id = {alias}.user_id;
                    END
                """)
