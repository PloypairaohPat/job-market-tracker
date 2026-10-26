-- Jobs first seen per UTC day, per source.
SELECT snapshot_date, source, new_jobs
FROM v_ingestion_daily
ORDER BY snapshot_date, source;
