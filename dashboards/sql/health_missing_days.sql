-- UTC days inside the window with no snapshot at all: lost for good, never backfilled.
WITH bounds AS (
    SELECT MIN(snapshot_date) AS lo, MAX(snapshot_date) AS hi FROM v_ingestion_daily
),
calendar AS (
    SELECT generate_series(lo, hi, INTERVAL '1 day')::date AS d FROM bounds
),
present AS (
    SELECT DISTINCT snapshot_date AS d FROM v_ingestion_daily
)
SELECT c.d AS missing_date, COUNT(*) OVER () AS n_missing_days
FROM calendar c
LEFT JOIN present p ON p.d = c.d
WHERE p.d IS NULL
ORDER BY c.d;
