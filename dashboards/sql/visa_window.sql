-- Data window for Visa outlook: snapshot dates covered and in-scope jobs classified.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily) AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily) AS last_snapshot,
    COUNT(*)                                           AS n_jobs,
    COUNT(*) FILTER (WHERE employer_matched)           AS n_employer_matched
FROM v_job_visa_outlook;
