-- Strong and possible jobs with the evidence. metro_area is the tracked-metro allowlist (instrument-limited).
SELECT
    bucket,
    title,
    company,
    COALESCE(metro_area, '(not a tracked metro)') AS metro,
    bucket_reason,
    certified_h1b_lcas,
    certified_h1b_analytics_soc_new_employment,
    redirect_url
FROM v_job_visa_outlook
WHERE bucket IN ('strong', 'possible')
ORDER BY ARRAY_POSITION(ARRAY['strong', 'possible'], bucket),
         certified_h1b_analytics_soc_new_employment DESC, job_id;
