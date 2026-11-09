-- Schema 7 -> 6 (SPEC-047). Run only after stopping application writes and verifying a schema-7 backup.
-- Business rows, audit history and credentials stay intact. run_tombstones and
-- mutation_receipts.recorded_at are kept: schema-6 code ignores them, and the next
-- schema-7 upgrade backfills tombstones for deletions made while rolled back.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_seven_rollback_guard (version TEXT NOT NULL CHECK (version = '7'));
INSERT INTO schema_seven_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
-- Schema-6 code still writes keyed run-creation receipts to this table.
CREATE TABLE IF NOT EXISTS run_creation_requests (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_key VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    response_json JSON NOT NULL,
    CONSTRAINT uq_run_request_user_key UNIQUE (user_id, request_key)
);
UPDATE schema_metadata SET value = '6' WHERE key = 'schema_version';
DROP TABLE schema_seven_rollback_guard;
COMMIT;
