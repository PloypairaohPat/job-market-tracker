-- Data window for Skills: snapshot dates covered and jobs per market behind the skill shares.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily) AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily) AS last_snapshot,
    market,
    MAX(market_n_jobs)                                 AS n_jobs
FROM v_skill_category_composition
GROUP BY market
ORDER BY market;
