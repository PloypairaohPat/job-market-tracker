-- v_analysis_population
--
-- The ANALYSIS POPULATION, defined once: one row per job that the market
-- comparisons count, labelled by market.
--
--   market = 'commercial' -> jobs.source = 'adzuna' (every row; the Adzuna
--                            queries are in scope by construction)
--   market = 'federal'    -> jobs.source = 'usajobs' AND jobs.in_scope
--                            (in_scope NULL or false is excluded; see
--                            docs/data_dictionary.md's jobs.in_scope section)
--
-- Any other source is excluded. The views that compare the two markets read
-- this view instead of repeating the filter, so a change to the population
-- is made here and nowhere else. It must sort before every view that reads
-- it (scripts/apply_views.py applies files in name order).
--
-- tests/test_analysis_population.py checks that every view built on it
-- returns exactly what its earlier inline filter returned.

CREATE OR REPLACE VIEW v_analysis_population AS
SELECT
    j.id AS job_id,
    CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market
FROM jobs j
WHERE j.source = 'adzuna'
   OR (j.source = 'usajobs' AND j.in_scope);
