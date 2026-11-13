-- v_employer_postings
--
-- Employer-level posting counts per market, for Phase 5 report 3 (who hires
-- data analysts, and how concentrated hiring is). Same populations as
-- v_market_jobs (commercial = every Adzuna posting; federal = USAJobs AND
-- in_scope), defined inline because this file sorts before v_market_jobs.sql.
--
-- One row per (market, employer_key). employer_key = companies.normalized_name,
-- the grouping key (aliases already folded by the cleaning layer). Postings
-- with no company (or no normalized name) form ONE row with employer_key NULL:
-- never an employer, but counted in market_n_postings.
--   employer_name       display only: the alphabetically first canonical_name
--                       under the key
--   n_postings          the employer's postings in the market
--   market_n_postings   every posting in the market: the denominator of a share
--   market_n_employers  distinct non-NULL employer_keys in the market
-- Aggregate only: no job-level columns.

CREATE OR REPLACE VIEW v_employer_postings AS
WITH population AS (
    SELECT
        CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        c.normalized_name AS employer_key,
        c.canonical_name
    FROM jobs j
    LEFT JOIN companies c ON c.id = j.company_id
    WHERE j.source = 'adzuna'
       OR (j.source = 'usajobs' AND j.in_scope)
),
totals AS (
    SELECT
        market,
        COUNT(*) AS market_n_postings,
        COUNT(DISTINCT employer_key) AS market_n_employers
    FROM population
    GROUP BY market
)
SELECT
    p.market,
    p.employer_key,
    MIN(p.canonical_name) AS employer_name,
    COUNT(*) AS n_postings,
    t.market_n_postings,
    t.market_n_employers
FROM population p
JOIN totals t ON t.market = p.market
GROUP BY p.market, p.employer_key, t.market_n_postings, t.market_n_employers
ORDER BY p.market, n_postings DESC, employer_name;
