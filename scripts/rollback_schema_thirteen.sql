-- Schema 13 -> 12 (SPEC-096). Run only after stopping application writes and verifying a schema-13 backup.
-- Business rows, audit history and credentials stay intact. Schema-12 code expects every month to equal its
-- adjustment plus all of that month's runs, so hike kilometres are added back to monthly_mileages first.
-- runs.activity_type is kept: schema-12 code never reads it (new runs default to 'road'), and the next
-- schema-13 upgrade takes the hike kilometres out of monthly_mileages again.
BEGIN IMMEDIATE;
CREATE TEMP TABLE schema_thirteen_rollback_guard (version TEXT NOT NULL CHECK (version = '13'));
INSERT INTO schema_thirteen_rollback_guard VALUES ((SELECT value FROM schema_metadata WHERE key = 'schema_version'));
INSERT INTO monthly_mileages (id, user_id, version, year, month, km, adjustment_km)
SELECT
    (SELECT coalesce(max(id), 0) FROM monthly_mileages)
        + row_number() OVER (ORDER BY hikes.user_id, hikes.year, hikes.month),
    hikes.user_id, 0, hikes.year, hikes.month, 0, 0
FROM (
    SELECT DISTINCT user_id,
        CAST(substr(date, 1, 4) AS INTEGER) AS year,
        CAST(substr(date, 6, 2) AS INTEGER) AS month
    FROM runs WHERE activity_type = 'hike'
) AS hikes
WHERE NOT EXISTS (
    SELECT 1 FROM monthly_mileages AS existing
    WHERE existing.user_id = hikes.user_id AND existing.year = hikes.year AND existing.month = hikes.month
);
UPDATE monthly_mileages SET km = round(km + (
    SELECT coalesce(sum(runs.km), 0) FROM runs
    WHERE runs.user_id = monthly_mileages.user_id AND runs.activity_type = 'hike'
    AND CAST(substr(runs.date, 1, 4) AS INTEGER) = monthly_mileages.year
    AND CAST(substr(runs.date, 6, 2) AS INTEGER) = monthly_mileages.month
), 2), version = version + 1
WHERE EXISTS (
    SELECT 1 FROM runs
    WHERE runs.user_id = monthly_mileages.user_id AND runs.activity_type = 'hike'
    AND CAST(substr(runs.date, 1, 4) AS INTEGER) = monthly_mileages.year
    AND CAST(substr(runs.date, 6, 2) AS INTEGER) = monthly_mileages.month
);
UPDATE entity_sequences SET next_id = max(next_id, (SELECT coalesce(max(id), 0) + 1 FROM monthly_mileages))
WHERE name = 'monthly_mileages';
UPDATE schema_metadata SET value = '12' WHERE key = 'schema_version';
DROP TABLE schema_thirteen_rollback_guard;
COMMIT;
