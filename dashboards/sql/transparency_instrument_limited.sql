-- INSTRUMENT-LIMITED fields: they measure our classifiers' reach, not market disclosure.
SELECT market, n_jobs, pct_seniority_present, pct_metro_present, pct_remote_true
FROM v_field_completeness
ORDER BY market;
