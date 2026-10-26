-- Data window for Skills: snapshot dates covered and the jobs per market behind the shares.
SELECT
    (SELECT MIN(snapshot_date) FROM v_ingestion_daily)                AS first_snapshot,
    (SELECT MAX(snapshot_date) FROM v_ingestion_daily)                AS last_snapshot,
    MAX(market_n_jobs) FILTER (WHERE market = 'commercial')           AS n_commercial_jobs,
    MAX(market_n_jobs) FILTER (WHERE market = 'federal')              AS n_federal_jobs
FROM v_skill_category_composition;
