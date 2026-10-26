-- Current streak: consecutive snapshot days ending today or yesterday (UTC), vs the 60-day target.
WITH days AS (
    SELECT DISTINCT snapshot_date AS d FROM v_ingestion_daily
),
today AS (
    SELECT (NOW() AT TIME ZONE 'UTC')::date AS t
),
anchor AS (
    SELECT CASE
               WHEN EXISTS (SELECT 1 FROM days, today WHERE d = t) THEN t
               WHEN EXISTS (SELECT 1 FROM days, today WHERE d = t - 1) THEN t - 1
           END AS a
    FROM today
),
islands AS (
    SELECT d, d - (ROW_NUMBER() OVER (ORDER BY d))::int AS grp FROM days
)
SELECT
    COALESCE((SELECT COUNT(*) FROM islands i
              WHERE i.grp = (SELECT grp FROM islands, anchor WHERE d = a)), 0) AS n_streak_days,
    60                                                                         AS target_days,
    (SELECT COUNT(*) FROM days)                                                AS n_snapshot_days;
