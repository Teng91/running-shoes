-- Schema 11 -> 10 (SPEC-075). Run only after stopping application writes and verifying a schema-11 backup.
-- Business rows, audit history and credentials stay intact. invites is kept: schema-10 code never reads
-- it (registration is open again under schema-10 code). The lower(username) index is dropped because
-- schema-10 code does not expect it; the next schema-11 upgrade recreates it.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_eleven_rollback_guard (version TEXT NOT NULL CHECK (version = '11'));
INSERT INTO schema_eleven_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
DROP INDEX IF EXISTS uq_users_username_lower;
UPDATE schema_metadata SET value = '10' WHERE key = 'schema_version';
DROP TABLE schema_eleven_rollback_guard;
COMMIT;
