-- v_market_jobs
--
-- One row per job in the ANALYSIS POPULATION, labelled by market, for the
-- Market overview dashboard (jobs by metro and source, seniority mix, top
-- employers). Cards aggregate over this view and show n beside every group.
--
-- Same population as v_skill_category_composition / v_field_completeness:
-- market = 'commercial' -> source='adzuna' (all rows; in_scope by construction).
-- market = 'federal'    -> source='usajobs' AND in_scope (the clean-series +
--   skill-density-admitted population; see docs/data_dictionary.md's
--   jobs.in_scope section). Out-of-scope federal postings are not here.
--
--   metro_area  INSTRUMENT-LIMITED: a lookup against an explicit tracked-metro
--               allowlist (src/cleaning/metro.py). NULL means "not on our
--               tracked list" (or no single parsable location), never "no
--               location given" -- label it that way, never as all locations.
--   seniority   INSTRUMENT-LIMITED: classified from the TITLE only
--               (src/cleaning/seniority.py). NULL means no title signal and is
--               NEVER folded into 'mid'.
--   employer_key    companies.normalized_name (the grouping key); NULL when
--                   the posting had no company.
--   employer_name   companies.canonical_name, for display only -- group by
--                   employer_key, not by this.
--
-- No salary columns: salary lives in v_commercial_salary_clean, where the
-- predicted/disclosed split is explicit.

CREATE OR REPLACE VIEW v_market_jobs AS
SELECT
    j.id                    AS job_id,
    CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
    j.source,
    l.metro_area,
    j.seniority,
    c.normalized_name       AS employer_key,
    c.canonical_name        AS employer_name,
    j.first_seen_at,
    j.last_seen_at
FROM jobs j
LEFT JOIN locations l ON l.id = j.location_id
LEFT JOIN companies c ON c.id = j.company_id
WHERE j.source = 'adzuna'
   OR (j.source = 'usajobs' AND j.in_scope);
