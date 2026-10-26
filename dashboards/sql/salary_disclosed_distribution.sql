-- Employer-DISCLOSED annual salary midpoints only, in $10k bins.
SELECT
    (FLOOR(salary_midpoint / 10000) * 10000)::int AS bin_start_usd,
    COUNT(*)                                      AS n
FROM v_commercial_salary_clean
WHERE salary_is_predicted = false
GROUP BY 1
ORDER BY 1;
