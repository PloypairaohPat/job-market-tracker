-- v_skill_category_composition
--
-- PRIMARY view for Phase 3 #2 (commercial vs federal skill demand): share of
-- skill tags per taxonomy category, per market — normalizes out the raw
-- text-volume confound (federal descriptions run ~13x longer than Adzuna's
-- ~500-char cap) by comparing composition, not magnitude.
--
-- market = 'commercial' -> source='adzuna' (all rows; in_scope by construction).
-- market = 'federal'    -> source='usajobs' AND in_scope (the 70-job clean-series +
--   skill-density-admitted population; see docs/data_dictionary.md's in_scope section).
--
-- Both markets read skills from job_skills as already extracted (title +
-- description_full-or-description) — commercial is native-truncated (~500
-- chars, Adzuna's own cap), federal is full text (~6.5K median). This
-- difference is the reason composition (share), not magnitude (rate), is the
-- primary cut here — see docs/findings_commercial_vs_federal_skills.md for
-- the truncation-placement caveat that applies to BOTH markets, not just federal.
--
-- confidence >= 0.8 fixed threshold, matching the salary-premium investigation.

CREATE OR REPLACE VIEW v_skill_category_composition AS
WITH population AS (
    SELECT id, 'commercial' AS market FROM jobs WHERE source = 'adzuna'
    UNION ALL
    SELECT id, 'federal' AS market FROM jobs WHERE source = 'usajobs' AND in_scope
),
market_totals AS (
    SELECT market, COUNT(*) AS n_jobs FROM population GROUP BY market
),
tags AS (
    SELECT p.market, sk.category, js.job_id
    FROM population p
    JOIN job_skills js ON js.job_id = p.id AND js.confidence >= 0.8
    JOIN skills sk ON sk.id = js.skill_id
)
SELECT
    t.market,
    t.category,
    COUNT(*) AS n_tags,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY t.market), 1) AS pct_of_tags,
    mt.n_jobs AS market_n_jobs
FROM tags t
JOIN market_totals mt ON mt.market = t.market
GROUP BY t.market, t.category, mt.n_jobs
ORDER BY t.market, n_tags DESC;
