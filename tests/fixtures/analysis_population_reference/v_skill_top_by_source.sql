-- v_skill_top_by_source
--
-- SUBORDINATE to v_skill_category_composition — the per-skill drill-down
-- (texture, not the headline finding). Every rate is exposed alongside its
-- raw count and the market's total job count so a consumer never reports a
-- percentage without the n behind it.
--
-- Deliberately does NOT apply a minimum-n floor — that's a reporting
-- decision, not a data decision (mirrors v_commercial_salary_clean leaving
-- salary_is_predicted unfiltered). The Phase 3 #2 write-up applies n>=5 for
-- federal and n>=15 for commercial when drawing the top-skills table; a
-- different consumer may choose differently, but must always show n.
--
-- Same population and confidence threshold as v_skill_category_composition.

CREATE OR REPLACE VIEW v_skill_top_by_source AS
WITH population AS (
    SELECT id, 'commercial' AS market FROM jobs WHERE source = 'adzuna'
    UNION ALL
    SELECT id, 'federal' AS market FROM jobs WHERE source = 'usajobs' AND in_scope
),
market_totals AS (
    SELECT market, COUNT(*) AS n_jobs FROM population GROUP BY market
)
SELECT
    p.market,
    sk.name,
    sk.category,
    COUNT(*) AS n_jobs_tagged,
    mt.n_jobs AS market_n_jobs,
    ROUND(100.0 * COUNT(*) / mt.n_jobs, 1) AS pct_of_jobs
FROM population p
JOIN job_skills js ON js.job_id = p.id AND js.confidence >= 0.8
JOIN skills sk ON sk.id = js.skill_id
JOIN market_totals mt ON mt.market = p.market
GROUP BY p.market, sk.name, sk.category, mt.n_jobs
ORDER BY p.market, n_jobs_tagged DESC;
