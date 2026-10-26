-- Data window for Salary: snapshot dates covered; disclosed and predicted rows counted separately.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily)        AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily)        AS last_snapshot,
    COUNT(*) FILTER (WHERE salary_is_predicted = false)       AS n_disclosed,
    COUNT(*) FILTER (WHERE salary_is_predicted)               AS n_predicted
FROM v_commercial_salary_clean;
