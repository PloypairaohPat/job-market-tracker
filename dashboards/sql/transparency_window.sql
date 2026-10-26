-- Data window for Transparency: snapshot dates covered and jobs per market.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily) AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily) AS last_snapshot,
    market,
    n_jobs
FROM v_field_completeness
ORDER BY market;
