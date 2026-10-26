-- Salary present (any figure, incl. Adzuna's model estimate) vs employer-disclosed, per market.
SELECT market, n_jobs, pct_salary_present, pct_salary_disclosed
FROM v_field_completeness
ORDER BY market;
