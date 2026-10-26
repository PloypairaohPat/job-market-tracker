-- Distinct jobs observed per UTC snapshot day, per source. A missing day is a gap, not a zero.
SELECT snapshot_date, source, distinct_jobs
FROM v_ingestion_daily
ORDER BY snapshot_date, source;
