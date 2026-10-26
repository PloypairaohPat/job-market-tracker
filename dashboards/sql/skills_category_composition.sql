-- Share of skill tags per taxonomy category, per market (composition, not magnitude).
SELECT market, category, pct_of_tags, n_tags, market_n_jobs
FROM v_skill_category_composition
ORDER BY market, pct_of_tags DESC;
