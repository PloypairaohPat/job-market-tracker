-- Disclosed-only median salary by seniority (title-only, instrument-limited), with n.
SELECT
    COALESCE(seniority, 'no title signal')                                     AS seniority,
    COUNT(*)                                                                   AS n,
    ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY salary_midpoint)::numeric) AS median_usd,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY salary_midpoint)::numeric) AS p25_usd,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY salary_midpoint)::numeric) AS p75_usd,
    COUNT(*) < 10                                                              AS small_n
FROM v_commercial_salary_clean
WHERE salary_is_predicted = false
GROUP BY 1
ORDER BY median_usd DESC;
