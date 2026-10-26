-- Jobs by market (commercial = Adzuna; federal = USAJobs, in-scope only).
SELECT market, COUNT(*) AS n_jobs
FROM v_market_jobs
GROUP BY market
ORDER BY market;
