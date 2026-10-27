-- v_federal_skill_by_admission
--
-- METHODS CHECK for the federal side of Phase 3 #2: skill tag rates within
-- each route by which a USAJobs posting entered the federal population
-- (jobs.scope_reason; see docs/data_dictionary.md, jobs.in_scope):
--   'series:<label>'         a clean occupational series (Data Science Series,
--                            Operations Research, Statistics)
--   'skill_density:<label>'  an ambiguous category admitted on skill density
--                            (the trailing ':<n>' skill count is dropped)
--
-- It regenerates the "Statistics tag is not circular" check in
-- docs/findings_commercial_vs_federal_skills.md: if the Statistics rate holds
-- in a route admitted by series code without a statistics label (Operations
-- Research), the federal ml_stats skew isn't the series label echoed back.
--
-- One row per (route, skill) for every skill tagged on ANY federal in-scope
-- job, zero counts included, so "0 of 14" is a row rather than a missing one.
-- If no federal job carries any tag, each route still has one row, with name
-- NULL. route_n_jobs is on every row; no minimum-n floor here (that's a
-- reporting decision). Same confidence >= 0.8 as the other skill views.

CREATE OR REPLACE VIEW v_federal_skill_by_admission AS
WITH federal AS (
    SELECT
        id,
        CASE
            WHEN scope_reason LIKE 'skill_density:%'
                THEN 'skill_density:' || split_part(scope_reason, ':', 2)
            ELSE scope_reason
        END AS admission_route
    FROM jobs
    WHERE source = 'usajobs' AND in_scope
),
routes AS (
    SELECT admission_route, COUNT(*) AS route_n_jobs
    FROM federal
    GROUP BY admission_route
),
tags AS (
    SELECT DISTINCT f.admission_route, f.id AS job_id, js.skill_id
    FROM federal f
    JOIN job_skills js ON js.job_id = f.id AND js.confidence >= 0.8
),
federal_skills AS (
    SELECT DISTINCT skill_id FROM tags
)
SELECT
    r.admission_route,
    sk.name,
    sk.category,
    COUNT(t.job_id) AS n_jobs_tagged,
    r.route_n_jobs,
    ROUND(100.0 * COUNT(t.job_id) / r.route_n_jobs, 1) AS pct_of_jobs
FROM routes r
LEFT JOIN federal_skills fs ON true
LEFT JOIN skills sk ON sk.id = fs.skill_id
LEFT JOIN tags t ON t.admission_route = r.admission_route AND t.skill_id = fs.skill_id
GROUP BY r.admission_route, sk.name, sk.category, r.route_n_jobs
ORDER BY r.admission_route, n_jobs_tagged DESC, sk.name;
