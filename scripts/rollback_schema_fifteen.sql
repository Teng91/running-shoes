-- Schema 15 -> 14 (SPEC-147). Run only after stopping application writes and verifying a schema-15 backup.
-- users.timezone is kept: schema-14 code never reads it and counts every account's "today" in Taiwan time,
-- and accounts it creates get the column default (Asia/Taipei). The next schema-15 upgrade reuses each
-- account's saved zone.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_fifteen_rollback_guard (version TEXT NOT NULL CHECK (version = '15'));
INSERT INTO schema_fifteen_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
UPDATE schema_metadata SET value = '14' WHERE key = 'schema_version';
DROP TABLE schema_fifteen_rollback_guard;
COMMIT;
