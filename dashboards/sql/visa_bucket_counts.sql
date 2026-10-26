-- In-scope jobs per visa-outlook bucket (closed > strong > possible > unknown).
SELECT bucket, COUNT(*) AS n_jobs
FROM v_job_visa_outlook
GROUP BY bucket
ORDER BY ARRAY_POSITION(ARRAY['strong', 'possible', 'unknown', 'closed'], bucket);
