-- Schema 9 -> 8 (SPEC-060). Run only after stopping application writes and verifying a schema-9 backup.
-- Business rows, audit history and credentials stay intact. runs.duration_seconds is kept:
-- schema-8 code never reads or writes it (new runs leave it NULL), and the next schema-9
-- upgrade uses the stored moving times again. A run whose distance was edited while rolled
-- back keeps its old moving time, so its derived pace follows the new distance.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_nine_rollback_guard (version TEXT NOT NULL CHECK (version = '9'));
INSERT INTO schema_nine_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
UPDATE schema_metadata SET value = '8' WHERE key = 'schema_version';
DROP TABLE schema_nine_rollback_guard;
COMMIT;
