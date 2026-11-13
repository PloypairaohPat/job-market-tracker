-- v_skill_text_basis
--
-- CONTEXT for every skill number in Phase 3 #2 (commercial vs federal skill
-- demand) and its Phase 5 report: what text the skill extractor read, per
-- market, and how many tags it found there. Same populations and the same
-- confidence >= 0.8 as v_skill_category_composition:
--   market = 'commercial' -> source='adzuna' (all rows)
--   market = 'federal'    -> source='usajobs' AND in_scope
--
-- The extractor reads title + (description_full, else description)
-- (src/cleaning/extract_skills.py). The *_text_chars columns measure that
-- description part (the title is left out): federal reads full announcement
-- text, commercial reads Adzuna's description, capped at about 500 characters.
--
--   n_full_text     jobs read from description_full (Adzuna never has one)
--   n_near_cap      jobs read from description only whose text is >= 480
--                   characters: at or near Adzuna's ~500-character cap. On
--                   those, an absent skill is as likely cut off as missing.
--   n_jobs_tagged   jobs with at least one skill tag at confidence >= 0.8
--   n_tags          skill tags at confidence >= 0.8. Per market this equals
--                   the sum of v_skill_category_composition.n_tags: it is the
--                   denominator of that view's pct_of_tags.
--
-- Counts only, each beside n_jobs; no rate is precomputed. A market with no
-- jobs has no row.

CREATE OR REPLACE VIEW v_skill_text_basis AS
WITH population AS (
    SELECT id, 'commercial' AS market, description, description_full
    FROM jobs WHERE source = 'adzuna'
    UNION ALL
    SELECT id, 'federal' AS market, description, description_full
    FROM jobs WHERE source = 'usajobs' AND in_scope
),
tagged AS (
    SELECT job_id, COUNT(*) AS n_tags
    FROM job_skills
    WHERE confidence >= 0.8
    GROUP BY job_id
)
SELECT
    p.market,
    COUNT(*) AS n_jobs,
    COUNT(*) FILTER (WHERE p.description_full IS NOT NULL) AS n_full_text,
    COUNT(*) FILTER (
        WHERE p.description_full IS NULL AND LENGTH(p.description) >= 480
    ) AS n_near_cap,
    percentile_cont(0.25) WITHIN GROUP (
        ORDER BY LENGTH(COALESCE(p.description_full, p.description, ''))
    ) AS p25_text_chars,
    percentile_cont(0.5) WITHIN GROUP (
        ORDER BY LENGTH(COALESCE(p.description_full, p.description, ''))
    ) AS median_text_chars,
    percentile_cont(0.75) WITHIN GROUP (
        ORDER BY LENGTH(COALESCE(p.description_full, p.description, ''))
    ) AS p75_text_chars,
    COUNT(t.job_id) AS n_jobs_tagged,
    COALESCE(SUM(t.n_tags), 0)::bigint AS n_tags
FROM population p
LEFT JOIN tagged t ON t.job_id = p.id
GROUP BY p.market
ORDER BY p.market;
