-- v_field_completeness_counts
--
-- The COUNTS behind v_field_completeness's percentages (Phase 3 #3, "how much
-- employers disclose"), so a report can show every rate with its numerator and
-- denominator instead of a bare percentage. Same populations and the same
-- field definitions as v_field_completeness, column for column:
--   n_<field>  = the COUNT(*) FILTER (...) behind pct_<field>
--   n_jobs     = the denominator of every one of them
-- plus n_salary_predicted (salary present AND salary_is_predicted = true:
-- Adzuna's model estimate occupying the salary field), which
-- v_field_completeness has no column for.
--
-- The Phase 5 report reads both views and checks that 100 * n_<field> / n_jobs
-- reproduces pct_<field>, so the two can't drift apart silently.
--
-- Which fields are market facts and which are INSTRUMENT-LIMITED is documented
-- in v_field_completeness.sql's header and docs/findings_field_completeness.md;
-- it applies here unchanged. n_skill_present counts a tag at ANY confidence,
-- as v_field_completeness does (the skill-demand views use >= 0.8).

CREATE OR REPLACE VIEW v_field_completeness_counts AS
WITH population AS (
    SELECT j.id, j.location_id, j.salary_min, j.salary_is_predicted,
           j.seniority, j.is_remote, j.company_id, j.posted_at,
           'commercial' AS market
    FROM jobs j
    WHERE j.source = 'adzuna'
    UNION ALL
    SELECT j.id, j.location_id, j.salary_min, j.salary_is_predicted,
           j.seniority, j.is_remote, j.company_id, j.posted_at,
           'federal' AS market
    FROM jobs j
    WHERE j.source = 'usajobs' AND j.in_scope
),
skill_flag AS (
    SELECT DISTINCT job_id FROM job_skills
),
metro_flag AS (
    SELECT l.id AS location_id, l.metro_area
    FROM locations l
)
SELECT
    p.market,
    COUNT(*) AS n_jobs,
    COUNT(*) FILTER (WHERE p.salary_min IS NOT NULL) AS n_salary_present,
    COUNT(*) FILTER (WHERE p.salary_min IS NOT NULL AND p.salary_is_predicted = false)
        AS n_salary_disclosed,
    COUNT(*) FILTER (WHERE p.salary_min IS NOT NULL AND p.salary_is_predicted = true)
        AS n_salary_predicted,
    COUNT(*) FILTER (WHERE sf.job_id IS NOT NULL) AS n_skill_present,
    COUNT(*) FILTER (WHERE p.seniority IS NOT NULL) AS n_seniority_present,
    COUNT(*) FILTER (WHERE p.location_id IS NOT NULL) AS n_location_present,
    COUNT(*) FILTER (WHERE mf.metro_area IS NOT NULL) AS n_metro_present,
    COUNT(*) FILTER (WHERE p.is_remote = true) AS n_remote_true,
    COUNT(*) FILTER (WHERE p.company_id IS NOT NULL) AS n_company_present,
    COUNT(*) FILTER (WHERE p.posted_at IS NOT NULL) AS n_posted_at_present
FROM population p
LEFT JOIN skill_flag sf ON sf.job_id = p.id
LEFT JOIN metro_flag mf ON mf.location_id = p.location_id
GROUP BY p.market
ORDER BY p.market;
