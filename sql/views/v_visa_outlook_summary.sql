-- v_visa_outlook_summary
--
-- v_job_visa_outlook aggregated: postings per (market, bucket, bucket_reason),
-- for Phase 5 report 3. That view is per job (titles, URLs) and feeds the
-- PRIVATE Visa outlook dashboard; this one carries counts only, so a report
-- can describe the buckets without ever loading a job row. Depends on
-- v_job_visa_outlook, which sorts before this file.
--
--   market             'commercial' (Adzuna) | 'federal' (USAJobs); the
--                      outlook view is already limited to in-scope jobs
--   bucket             closed | strong | possible | unknown (thresholds are
--                      the visa layer's defaults, unchanged)
--   bucket_reason      the rule that fired, as v_job_visa_outlook names it
--   n_postings         postings with that bucket and reason
--   market_n_postings  every in-scope posting in the market: the denominator
--
-- "unknown" is never "no" (no signal, no employer match, or the visa step
-- hasn't run), and "strong" is never "yes". See src/visa/README.md, "What this
-- can't tell you".

CREATE OR REPLACE VIEW v_visa_outlook_summary AS
WITH outlook AS (
    SELECT
        CASE WHEN source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        bucket,
        bucket_reason
    FROM v_job_visa_outlook
    WHERE source IN ('adzuna', 'usajobs')
),
totals AS (
    SELECT market, COUNT(*) AS market_n_postings
    FROM outlook
    GROUP BY market
)
SELECT
    o.market,
    o.bucket,
    o.bucket_reason,
    COUNT(*) AS n_postings,
    t.market_n_postings
FROM outlook o
JOIN totals t ON t.market = o.market
GROUP BY o.market, o.bucket, o.bucket_reason, t.market_n_postings
ORDER BY o.market, o.bucket, n_postings DESC, o.bucket_reason;
