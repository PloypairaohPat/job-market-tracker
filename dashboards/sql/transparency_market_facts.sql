-- Fields whose completeness is a market fact (skills is capped by commercial truncation).
SELECT market, n_jobs, pct_skill_present, pct_location_present, pct_company_present, pct_posted_at_present
FROM v_field_completeness
ORDER BY market;
