-- Comparison only: Adzuna-predicted vs employer-disclosed, side by side, never blended.
SELECT
    CASE WHEN salary_is_predicted THEN 'Adzuna-predicted' ELSE 'employer-disclosed' END AS salary_source,
    COUNT(*)                                                                         AS n,
    ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY salary_midpoint)::numeric)    AS median_usd,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY salary_midpoint)::numeric)    AS p25_usd,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY salary_midpoint)::numeric)    AS p75_usd
FROM v_commercial_salary_clean
GROUP BY salary_is_predicted
ORDER BY salary_is_predicted;
