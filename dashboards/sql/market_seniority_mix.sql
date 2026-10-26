-- Seniority mix per market, from titles only (instrument-limited). NULL = no title signal, never "mid".
SELECT
    market,
    COALESCE(seniority, 'no title signal')                                  AS seniority,
    COUNT(*)                                                                AS n_jobs,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY market), 1)   AS pct_of_market,
    SUM(COUNT(*)) OVER (PARTITION BY market)                                AS n_market_jobs
FROM v_market_jobs
GROUP BY market, 2
ORDER BY market, n_jobs DESC;
