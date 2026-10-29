-- v_salary_population
--
-- Who is measured, for Phase 5 report 4 (what commercial data-analyst
-- postings pay): every commercial (Adzuna) posting, grouped by the four
-- fields that decide whether its salary is usable. One row per
-- (salary_quality, salary_currency, salary_period, salary_is_predicted);
-- NULLs form their own groups (salary_quality NULL = no salary at all).
--
--   n                    postings in the group
--   in_clean_population  true for the groups v_commercial_salary_clean keeps
--                        (salary_quality = 'ok' AND USD AND period = 'year');
--                        the sum of n over them equals count(*) of that view
--   market_n_postings    every commercial posting: the denominator
--
-- Adzuna returns a salary for nearly every posting because its model fills
-- in the ones employers didn't disclose (salary_is_predicted = true), so
-- "has a salary" is API behaviour; the employer-disclosed share is the
-- market fact. Aggregate only: no job-level columns.

CREATE OR REPLACE VIEW v_salary_population AS
SELECT
    j.salary_quality,
    j.salary_currency,
    j.salary_period,
    j.salary_is_predicted,
    COUNT(*) AS n,
    COALESCE(
        j.salary_quality = 'ok' AND j.salary_currency = 'USD' AND j.salary_period = 'year',
        false
    ) AS in_clean_population,
    (SUM(COUNT(*)) OVER ())::bigint AS market_n_postings
FROM jobs j
WHERE j.source = 'adzuna'
GROUP BY j.salary_quality, j.salary_currency, j.salary_period, j.salary_is_predicted
ORDER BY n DESC, j.salary_quality, j.salary_currency, j.salary_period, j.salary_is_predicted;
