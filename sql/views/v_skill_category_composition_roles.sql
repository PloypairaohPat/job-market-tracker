-- v_skill_category_composition_roles
--
-- SENSITIVITY companion of v_skill_category_composition (which stays the
-- primary view): the same output shape, counted over distinct ROLES instead
-- of postings, so one role reposted in many places counts once. Read by
-- report 1's "Sensitivity: distinct roles" table; its primary numbers and
-- headline are unchanged.
--
-- A role is a (market, employer_key, normalized title) triple, as in
-- v_employer_roles: employer_key = companies.normalized_name, title =
-- COALESCE(NULLIF(title_normalized, ''), LOWER(TRIM(title))). Postings with
-- no company have no role (a role needs an employer), so they are left out
-- here. A role carries a category if ANY of its postings is tagged with a
-- skill of that category at confidence >= 0.8 (the skill views' threshold).
-- Same populations as v_skill_category_composition: commercial = every
-- Adzuna posting; federal = USAJobs AND in_scope.
--
--   n_tags         roles carrying the category (one per role per category,
--                  whatever the number of postings or skills behind it)
--   pct_of_tags    that, as a share of the market's role-category pairs
--   market_n_jobs  the market's distinct roles (the same column name as the
--                  primary view, so the two read alike; here it counts roles)
--
-- A sensitivity measure, not a dedup: identical titles at one employer can be
-- different jobs, and small wording variants count as separate roles.

CREATE OR REPLACE VIEW v_skill_category_composition_roles AS
WITH population AS (
    SELECT
        j.id,
        CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        c.normalized_name AS employer_key,
        COALESCE(NULLIF(j.title_normalized, ''), LOWER(TRIM(j.title))) AS role_title
    FROM jobs j
    LEFT JOIN companies c ON c.id = j.company_id
    WHERE j.source = 'adzuna'
       OR (j.source = 'usajobs' AND j.in_scope)
),
roles AS (
    SELECT DISTINCT market, employer_key, role_title
    FROM population
    WHERE employer_key IS NOT NULL
),
market_totals AS (
    SELECT market, COUNT(*) AS n_jobs FROM roles GROUP BY market
),
role_categories AS (
    SELECT DISTINCT p.market, p.employer_key, p.role_title, sk.category
    FROM population p
    JOIN job_skills js ON js.job_id = p.id AND js.confidence >= 0.8
    JOIN skills sk ON sk.id = js.skill_id
    WHERE p.employer_key IS NOT NULL
)
SELECT
    t.market,
    t.category,
    COUNT(*) AS n_tags,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY t.market), 1) AS pct_of_tags,
    mt.n_jobs AS market_n_jobs
FROM role_categories t
JOIN market_totals mt ON mt.market = t.market
GROUP BY t.market, t.category, mt.n_jobs
ORDER BY t.market, n_tags DESC;
