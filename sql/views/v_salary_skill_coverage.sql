-- v_salary_skill_coverage
--
-- Why report 4 computes no skill premiums: how thinly each salary basis of
-- the clean population (v_commercial_salary_clean, which sorts before this
-- file) carries skill tags. One row per basis, both always present:
--
--   basis              'employer-disclosed' (salary_is_predicted = false) or
--                      'Adzuna-predicted' (true); rows with the flag NULL
--                      belong to neither and are left out
--   n_jobs             clean postings of that basis
--   n_jobs_tagged      of those, with any skill tag at confidence >= 0.8
--   largest_skill_n    postings carrying the single most common skill
--   n_skills_at_floor  skills carried by at least 15 postings: the salary
--                      reporting floor (SALARY_FLOOR in
--                      src/reports/guardrails.py; a test keeps them equal)
--
-- Same confidence threshold and join as the skill views
-- (job_skills.confidence >= 0.8). Commercial skill counts are truncation-
-- floored: Adzuna descriptions are cut at about 500 characters. Even a basis
-- that reaches the floor gets no premium computed: see
-- docs/findings_skill_premium_deferred.md. Aggregate only.

CREATE OR REPLACE VIEW v_salary_skill_coverage AS
WITH bases(basis, is_predicted) AS (
    VALUES ('employer-disclosed', false), ('Adzuna-predicted', true)
),
clean AS (
    SELECT c.job_id, b.basis
    FROM v_commercial_salary_clean c
    JOIN bases b ON b.is_predicted = c.salary_is_predicted
),
tagged AS (
    SELECT c.basis, c.job_id, js.skill_id
    FROM clean c
    JOIN job_skills js ON js.job_id = c.job_id AND js.confidence >= 0.8
),
per_skill AS (
    SELECT basis, skill_id, COUNT(DISTINCT job_id) AS n
    FROM tagged
    GROUP BY basis, skill_id
)
SELECT
    b.basis,
    (SELECT COUNT(*) FROM clean c WHERE c.basis = b.basis) AS n_jobs,
    (SELECT COUNT(DISTINCT t.job_id) FROM tagged t WHERE t.basis = b.basis) AS n_jobs_tagged,
    COALESCE((SELECT MAX(n) FROM per_skill s WHERE s.basis = b.basis), 0) AS largest_skill_n,
    (SELECT COUNT(*) FROM per_skill s WHERE s.basis = b.basis AND s.n >= 15) AS n_skills_at_floor
FROM bases b
ORDER BY b.is_predicted;
