-- Schema 8 -> 7 (SPEC-055). Run only after stopping application writes and verifying a schema-8 backup.
-- Business rows, audit history and credentials stay intact. run_tombstones.strava_id and
-- its index are kept: schema-7 code never reads or writes them, and the next schema-8
-- upgrade fills strava_id for runs deleted while rolled back (from retained audit rows).
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_eight_rollback_guard (version TEXT NOT NULL CHECK (version = '8'));
INSERT INTO schema_eight_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
UPDATE schema_metadata SET value = '7' WHERE key = 'schema_version';
DROP TABLE schema_eight_rollback_guard;
COMMIT;
