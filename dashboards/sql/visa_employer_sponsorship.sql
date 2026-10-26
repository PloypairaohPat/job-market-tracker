-- Employer sponsorship aggregates over the last 3 loaded fiscal years (LCA filings, not hires).
SELECT
    employer_key,
    window_start_fy,
    window_end_fy,
    certified_h1b_lcas,
    certified_h1b_new_employment,
    certified_h1b_analytics_soc,
    certified_h1b_analytics_soc_new_employment,
    wage_level_i, wage_level_ii, wage_level_iii, wage_level_iv, wage_level_na_or_missing,
    ROUND(median_offered_annual_wage::numeric) AS median_offered_annual_wage,
    n_lcas_all_statuses,
    any_h1b_dependent,
    any_willful_violator
FROM v_employer_sponsorship
WHERE period = 'last_3_fy'
ORDER BY certified_h1b_lcas DESC, employer_key
LIMIT 25;
