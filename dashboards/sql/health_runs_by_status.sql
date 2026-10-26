-- Runs per source and final status, all time.
SELECT source, status, COUNT(*) AS n_runs, SUM(calls_made) AS calls_made
FROM v_ingestion_runs
GROUP BY source, status
ORDER BY source, status;
