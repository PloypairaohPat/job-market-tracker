-- Jobs by tracked metro and market. metro_area is an allowlist lookup (instrument-limited):
-- NULL means "not a tracked metro", not "no location".
SELECT
    COALESCE(metro_area, '(not a tracked metro)') AS metro,
    market,
    COUNT(*)                                      AS n_jobs,
    COUNT(*) < 10                                 AS small_n
FROM v_market_jobs
GROUP BY 1, 2
ORDER BY n_jobs DESC, metro, market;
