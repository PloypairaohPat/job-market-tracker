-- v_employer_roles
--
-- Distinct roles beside postings, per employer and market, for Phase 5 report
-- 3: how much of an employer's posting count is the same role reposted (one
-- title in many locations, or re-listed). Same populations as
-- v_employer_postings (commercial = every Adzuna posting; federal = USAJobs
-- AND in_scope), defined inline, and the same rows: one per (market,
-- employer_key), plus ONE row per market for postings with no company
-- (employer_key NULL). That row's postings count, but it has no roles, since
-- a role needs an employer.
--
-- A ROLE is an (employer, normalized title) pair. The title is
-- jobs.title_normalized (lowercased, whitespace collapsed by the parsers), or
-- LOWER(TRIM(title)) where that is empty. It is a sensitivity measure, NOT a
-- dedup: identical titles at one employer can be different jobs (so roles
-- undercount), and small wording variants of one job count separately (so
-- roles overcount). Read it beside the posting count, never instead of it.
--
--   n_postings         the employer's postings in the market
--   n_roles            distinct normalized titles among them (0 for NULL)
--   n_locations        distinct location_id among them (postings with no
--                      location don't add one)
--   market_n_postings  every posting in the market (as v_employer_postings)
--   market_n_roles     distinct roles in the market: the sum of n_roles
-- Aggregate only: no job-level columns, and no title.

CREATE OR REPLACE VIEW v_employer_roles AS
WITH population AS (
    SELECT
        CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        c.normalized_name AS employer_key,
        COALESCE(NULLIF(j.title_normalized, ''), LOWER(TRIM(j.title))) AS role_title,
        j.location_id
    FROM jobs j
    LEFT JOIN companies c ON c.id = j.company_id
    WHERE j.source = 'adzuna'
       OR (j.source = 'usajobs' AND j.in_scope)
),
per_employer AS (
    SELECT
        market,
        employer_key,
        COUNT(*) AS n_postings,
        CASE WHEN employer_key IS NULL THEN 0 ELSE COUNT(DISTINCT role_title) END AS n_roles,
        COUNT(DISTINCT location_id) AS n_locations
    FROM population
    GROUP BY market, employer_key
)
SELECT
    market,
    employer_key,
    n_postings,
    n_roles,
    n_locations,
    SUM(n_postings) OVER (PARTITION BY market)::bigint AS market_n_postings,
    SUM(n_roles) OVER (PARTITION BY market)::bigint AS market_n_roles
FROM per_employer
ORDER BY market, n_roles DESC, employer_key;
