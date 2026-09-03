-- v_field_completeness
--
-- PRIMARY view for Phase 3 #3 ("what these postings actually tell you"):
-- per-source, per-field completeness. One row per market ('commercial' |
-- 'federal'), every candidate-relevant field as its own PRESENT% column,
-- plus the two-layer PRESENT-vs-INFORMATIVE columns for the fields where
-- that distinction is real (salary, skills, metro).
--
-- market = 'commercial' -> source='adzuna' (all rows; in_scope by construction).
-- market = 'federal'    -> source='usajobs' AND in_scope (the 70-job clean
--   population; see docs/data_dictionary.md's jobs.in_scope section).
--
-- Deliberately NOT pooled across sources (see docs/phase_3_findings.md
-- recon rule #1) -- a blended completeness number is a category error when
-- the two sources have structurally different slots (federal always
-- discloses salary by law; commercial discloses by choice).
--
-- Reading this view -- which columns are a market fact vs instrument-limited
-- (see docs/findings_field_completeness.md for the full recon backing each
-- label):
--   pct_salary_present     market fact (both sources ~100%)
--   pct_salary_disclosed   market fact -- THE headline two-layer split
--   pct_skill_present      market fact, capped by commercial truncation
--                          (Adzuna ~500-char cap; see v_skill_category_composition.sql)
--   pct_seniority_present  INSTRUMENT-LIMITED: classify_seniority() reads the
--                          TITLE ONLY (src/cleaning/seniority.py) -- this
--                          measures "% of titles with an explicit marker",
--                          never "% disclosed". A recon sample (n=15,
--                          commercial NULLs) found 2/15 descriptions carried
--                          an explicit years-of-experience cue invisible to a
--                          title-only classifier -- too small to correct the
--                          rate, large enough that the NULL can't be read as
--                          pure market silence.
--   pct_location_present   market fact -- has ANY parsed location at all.
--   pct_metro_present      INSTRUMENT-LIMITED: metro_area is a lookup against
--                          an explicit 8-city+DC allowlist (src/cleaning/metro.py),
--                          never a default/fallback. A NULL here means "not on
--                          our tracked list", not "no location given" -- see
--                          pct_location_present for the real disclosure rate.
--   pct_remote_true        market fact for commercial; INSTRUMENT-LIMITED for
--                          federal -- apply_remote() (src/cleaning/apply_cleaning.py)
--                          scans jobs.description only, never description_full,
--                          for every source. Harmless for commercial (description
--                          IS the only text available) but federal's telework
--                          policy lives in description_full's boilerplate
--                          ("Telework: Ad-hoc" etc): 12/70 federal jobs mention
--                          remote/telework there and nowhere the classifier reads.
--                          Federal's 0% is not a measured market rate.
--   pct_company_present,
--   pct_posted_at_present  market fact, near-100% both sources, not a focus.

CREATE OR REPLACE VIEW v_field_completeness AS
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

    ROUND(100.0 * COUNT(*) FILTER (WHERE p.salary_min IS NOT NULL) / COUNT(*), 1)
        AS pct_salary_present,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.salary_min IS NOT NULL AND p.salary_is_predicted = false) / COUNT(*), 1)
        AS pct_salary_disclosed,

    ROUND(100.0 * COUNT(*) FILTER (WHERE sf.job_id IS NOT NULL) / COUNT(*), 1)
        AS pct_skill_present,

    ROUND(100.0 * COUNT(*) FILTER (WHERE p.seniority IS NOT NULL) / COUNT(*), 1)
        AS pct_seniority_present,

    ROUND(100.0 * COUNT(*) FILTER (WHERE p.location_id IS NOT NULL) / COUNT(*), 1)
        AS pct_location_present,
    ROUND(100.0 * COUNT(*) FILTER (WHERE mf.metro_area IS NOT NULL) / COUNT(*), 1)
        AS pct_metro_present,

    ROUND(100.0 * COUNT(*) FILTER (WHERE p.is_remote = true) / COUNT(*), 1)
        AS pct_remote_true,

    ROUND(100.0 * COUNT(*) FILTER (WHERE p.company_id IS NOT NULL) / COUNT(*), 1)
        AS pct_company_present,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.posted_at IS NOT NULL) / COUNT(*), 1)
        AS pct_posted_at_present

FROM population p
LEFT JOIN skill_flag sf ON sf.job_id = p.id
LEFT JOIN metro_flag mf ON mf.location_id = p.location_id
GROUP BY p.market
ORDER BY p.market;
