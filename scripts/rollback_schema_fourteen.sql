-- Schema 14 -> 13 (SPEC-119). Run only after stopping application writes and verifying a schema-14 backup.
-- race_goals.plan_weeks is kept: schema-13 code never reads it, its plans use each distance's default
-- length, and new goals saved by schema-13 code leave it NULL. The next schema-14 upgrade reuses it.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_fourteen_rollback_guard (version TEXT NOT NULL CHECK (version = '14'));
INSERT INTO schema_fourteen_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
UPDATE schema_metadata SET value = '13' WHERE key = 'schema_version';
DROP TABLE schema_fourteen_rollback_guard;
COMMIT;
