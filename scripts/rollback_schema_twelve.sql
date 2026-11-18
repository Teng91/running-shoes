-- Schema 12 -> 11 (SPEC-079). Run only after stopping application writes and verifying a schema-12 backup.
-- Business rows, audit history and credentials stay intact. users.email and email_codes are kept: schema-11
-- code never reads them (no email recovery), and the next schema-12 upgrade uses them again. The partial
-- lower(email) index is dropped because schema-11 code does not expect it; the upgrade recreates it.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_twelve_rollback_guard (version TEXT NOT NULL CHECK (version = '12'));
INSERT INTO schema_twelve_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
DROP INDEX IF EXISTS uq_users_email_lower;
UPDATE schema_metadata SET value = '11' WHERE key = 'schema_version';
DROP TABLE schema_twelve_rollback_guard;
COMMIT;
