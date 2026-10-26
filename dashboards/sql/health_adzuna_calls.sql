-- Adzuna API calls per day from the run log (NULL = no run row: before the log existed).
SELECT snapshot_date, calls_made
FROM v_ingestion_daily
WHERE source = 'adzuna'
ORDER BY snapshot_date;
