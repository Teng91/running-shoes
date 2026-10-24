-- Run only after stopping application writes and verifying a schema-6 backup.
-- Only temporary previews are discarded; business rows and credentials stay intact.
BEGIN IMMEDIATE;
CREATE TEMP TABLE preview_rollback_guard (version TEXT NOT NULL CHECK (version = '6'));
INSERT INTO preview_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
CREATE TABLE restore_previews_v5 (
    user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id),
    token VARCHAR(36) NOT NULL,
    revision INTEGER NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    payload_json JSON NOT NULL,
    expires_at DATETIME NOT NULL
);
DROP TABLE restore_previews;
ALTER TABLE restore_previews_v5 RENAME TO restore_previews;
UPDATE schema_metadata SET value = '5' WHERE key = 'schema_version';
DROP TABLE preview_rollback_guard;
COMMIT;
