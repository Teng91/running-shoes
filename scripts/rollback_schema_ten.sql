-- Schema 10 -> 9 (SPEC-065). Run only after stopping application writes and verifying a schema-10 backup.
-- Business rows, audit history and credentials stay intact. race_goals is kept: schema-9 code
-- never reads or writes it, and the next schema-10 upgrade uses the stored race goal again.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_ten_rollback_guard (version TEXT NOT NULL CHECK (version = '10'));
INSERT INTO schema_ten_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
UPDATE schema_metadata SET value = '9' WHERE key = 'schema_version';
DROP TABLE schema_ten_rollback_guard;
COMMIT;
