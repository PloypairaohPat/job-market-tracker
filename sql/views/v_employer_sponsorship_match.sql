-- v_employer_sponsorship_match
--
-- How many postings and employers, per market, match an employer with LCA
-- (H-1B) filing history, for Phase 5 report 3. Same populations as
-- v_employer_postings. The match is the visa layer's own: employer_key
-- (companies.normalized_name) = v_employer_sponsorship.employer_key with
-- period = 'last_3_fy' (the latest loaded FY and the two before it). Near-miss
-- names are reviewed through src/visa/sponsor_match.py; nothing is fuzzy here.
--
-- Three nested levels, each counted for postings and for employers:
--   matched        the employer has any LCA filing in the window (any status)
--   certified_h1b  ... and >= 1 certified H-1B LCA in the window
--   analytics_soc  ... and >= 1 certified H-1B LCA for an analytics SOC code
--                  (v_employer_sponsorship's list, unchanged)
-- An employer that doesn't match is "no match found", never "doesn't sponsor":
-- names differ between postings and DOL's file, and employers file under other
-- entities. An LCA is a FILING, not an approval or a hire. See
-- src/visa/README.md, "What this can't tell you".
--
-- n_postings and n_employers are the denominators (no-company postings are
-- counted in n_postings and can never match). lca_rows_loaded is every row in
-- lca_cases: 0 means the LCA files haven't been loaded, and every match
-- count is then 0 for that reason alone. The window columns are NULL then.
-- Aggregate only.

CREATE OR REPLACE VIEW v_employer_sponsorship_match AS
WITH population AS (
    SELECT
        CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        c.normalized_name AS employer_key
    FROM jobs j
    LEFT JOIN companies c ON c.id = j.company_id
    WHERE j.source = 'adzuna'
       OR (j.source = 'usajobs' AND j.in_scope)
),
lca AS (
    SELECT
        employer_key,
        certified_h1b_lcas > 0 AS has_certified_h1b,
        certified_h1b_analytics_soc > 0 AS has_analytics_soc
    FROM v_employer_sponsorship
    WHERE period = 'last_3_fy'
),
loaded AS (
    SELECT COUNT(*) AS lca_rows_loaded, MAX(fiscal_year) AS window_end_fy
    FROM lca_cases
),
flagged AS (
    SELECT
        p.market,
        p.employer_key,
        (l.employer_key IS NOT NULL) AS matched,
        COALESCE(l.has_certified_h1b, false) AS certified_h1b,
        COALESCE(l.has_analytics_soc, false) AS analytics_soc
    FROM population p
    LEFT JOIN lca l ON l.employer_key = p.employer_key
)
SELECT
    f.market,
    COUNT(*) AS n_postings,
    COUNT(*) FILTER (WHERE f.employer_key IS NULL) AS n_postings_no_employer,
    COUNT(*) FILTER (WHERE f.matched) AS n_postings_matched,
    COUNT(*) FILTER (WHERE f.certified_h1b) AS n_postings_certified_h1b,
    COUNT(*) FILTER (WHERE f.analytics_soc) AS n_postings_analytics_soc,
    COUNT(DISTINCT f.employer_key) AS n_employers,
    COUNT(DISTINCT f.employer_key) FILTER (WHERE f.matched) AS n_employers_matched,
    COUNT(DISTINCT f.employer_key) FILTER (WHERE f.certified_h1b) AS n_employers_certified_h1b,
    COUNT(DISTINCT f.employer_key) FILTER (WHERE f.analytics_soc) AS n_employers_analytics_soc,
    ld.lca_rows_loaded,
    ld.window_end_fy - 2 AS lca_window_start_fy,
    ld.window_end_fy AS lca_window_end_fy
FROM flagged f
CROSS JOIN loaded ld
GROUP BY f.market, ld.lca_rows_loaded, ld.window_end_fy
ORDER BY f.market;
