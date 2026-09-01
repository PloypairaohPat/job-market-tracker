-- v_commercial_salary_clean
--
-- One row per commercial (Adzuna) job with a trustworthy annual USD salary:
-- salary_quality = 'ok' AND salary_currency = 'USD' AND salary_period = 'year'.
--
-- Deliberately does NOT filter on salary_is_predicted — both employer-disclosed
-- and Adzuna-modeled rows are exposed so downstream queries can either isolate
-- the disclosed anchor (WHERE salary_is_predicted = false) or run the explicit
-- predicted-vs-disclosed comparison. Any analysis reporting a headline salary
-- number must filter to salary_is_predicted = false; predicted rows are for
-- the comparison only, never blended silently into a "the" salary figure.
--
-- seniority is passed through as-is: NULL means no signal (a bare title with
-- no seniority cue), never coerced to 'mid'. Bucket accordingly downstream.

CREATE OR REPLACE VIEW v_commercial_salary_clean AS
SELECT
    j.id                            AS job_id,
    j.title,
    j.salary_min,
    j.salary_max,
    (j.salary_min + j.salary_max) / 2.0 AS salary_midpoint,
    j.salary_is_predicted,
    j.seniority,
    l.metro_area
FROM jobs j
LEFT JOIN locations l ON l.id = j.location_id
WHERE j.source = 'adzuna'
  AND j.salary_quality = 'ok'
  AND j.salary_currency = 'USD'
  AND j.salary_period = 'year';
