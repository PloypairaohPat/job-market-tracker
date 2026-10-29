-- v_employer_sponsorship
--
-- Employer-level H-1B sponsorship history from DOL's public LCA disclosure
-- files (lca_cases, loaded by src/visa/lca_loader.py). One row per
-- (employer_key, period):
--   period = 'FY<year>'   one row per fiscal year loaded (period_fy = year)
--   period = 'last_3_fy'  the latest loaded FY and the two before it
--                         (window_start_fy..window_end_fy; period_fy NULL)
-- The window is data-relative (anchored on MAX(fiscal_year) in lca_cases,
-- not today's date) so the view is deterministic and recomputable; it
-- only reaches "now" once the newest FY's file has been loaded.
--
-- An LCA is a FILING, not an approved H-1B petition and not a hire. Counts
-- favour large filers (staffing firms included) -- read every number as
-- "this employer has filed for this kind of role", never as "will sponsor
-- you". See src/visa/README.md, "What this can't tell you".
--
-- "Certified H-1B" = case_status = 'Certified' AND visa_class = 'H-1B'.
-- Certified - Withdrawn (the employer withdrew after certification), Denied
-- and Withdrawn are excluded, as are E-3 / H-1B1 (treaty visas F-1 holders
-- can't use). n_lcas_all_statuses keeps the unfiltered total for context.
--
-- Analytics SOC list (matched on the first 7 characters of soc_code, so
-- 15-2051.01 Business Intelligence Analysts counts under 15-2051). A
-- default pending the owner's confirmation -- parked in
-- docs/overnight-visa-layer.md. Edit ONLY here:
--   15-2051 Data Scientists (incl. .01 Business Intelligence Analysts)
--   15-2041 Statisticians
--   15-2031 Operations Research Analysts
--   13-1161 Market Research Analysts and Marketing Specialists
--   15-1211 Computer Systems Analysts
--   13-1111 Management Analysts
--   15-1243 Database Architects
--   13-2051 Financial and Investment Analysts
--
-- Offered annual wage = wage_rate_of_pay_from annualized by
-- wage_unit_of_pay: Hour x 2080, Week x 52, Bi-Weekly x 26, Month x 12,
-- Year x 1. Any other (or missing) unit -> NULL, counted in
-- n_wage_unit_unconvertible; median_offered_annual_wage ignores NULLs.
--
-- Wage level mix (pw_wage_level, certified H-1B only): from FY2027 the cap
-- lottery is weighted by OEWS level (IV = 4 entries ... I = 1), so an
-- employer whose filings sit at level I/II gives a lower-odds entry.
--
-- any_h1b_dependent / any_willful_violator look at ALL filings in the
-- period (any status or visa class): one flagged filing is enough.

CREATE OR REPLACE VIEW v_employer_sponsorship AS
WITH analytics_soc(soc_prefix) AS (
    VALUES ('15-2051'), ('15-2041'), ('15-2031'), ('13-1161'),
           ('15-1211'), ('13-1111'), ('15-1243'), ('13-2051')
),
cases AS (
    SELECT
        c.employer_key,
        c.fiscal_year,
        (c.case_status = 'Certified' AND c.visa_class = 'H-1B') AS is_cert_h1b,
        COALESCE(c.new_employment, 0) > 0 AS is_new_employment,
        (LEFT(c.soc_code, 7) IN (SELECT soc_prefix FROM analytics_soc)) AS is_analytics_soc,
        UPPER(TRIM(c.pw_wage_level)) AS wage_level,
        CASE LOWER(TRIM(c.wage_unit_of_pay))
            WHEN 'hour'      THEN c.wage_rate_of_pay_from * 2080
            WHEN 'week'      THEN c.wage_rate_of_pay_from * 52
            WHEN 'bi-weekly' THEN c.wage_rate_of_pay_from * 26
            WHEN 'month'     THEN c.wage_rate_of_pay_from * 12
            WHEN 'year'      THEN c.wage_rate_of_pay_from
        END AS offered_annual_wage,
        (LOWER(TRIM(c.wage_unit_of_pay)) IN ('hour', 'week', 'bi-weekly', 'month', 'year'))
            IS NOT TRUE AS is_wage_unit_unconvertible,
        c.decision_date,
        c.h1b_dependent,
        c.willful_violator
    FROM lca_cases c
    WHERE c.employer_key IS NOT NULL
),
fy_window AS (
    SELECT MAX(fiscal_year) AS end_fy FROM lca_cases
),
periods AS (
    SELECT cs.*, 'FY' || cs.fiscal_year AS period, cs.fiscal_year AS period_fy,
           cs.fiscal_year AS window_start_fy, cs.fiscal_year AS window_end_fy
    FROM cases cs
    UNION ALL
    SELECT cs.*, 'last_3_fy' AS period, NULL::int AS period_fy,
           w.end_fy - 2 AS window_start_fy, w.end_fy AS window_end_fy
    FROM cases cs
    CROSS JOIN fy_window w
    WHERE cs.fiscal_year BETWEEN w.end_fy - 2 AND w.end_fy
)
SELECT
    p.employer_key,
    p.period,
    p.period_fy,
    p.window_start_fy,
    p.window_end_fy,
    COUNT(*) AS n_lcas_all_statuses,
    COUNT(*) FILTER (WHERE p.is_cert_h1b) AS certified_h1b_lcas,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.is_new_employment) AS certified_h1b_new_employment,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.is_analytics_soc) AS certified_h1b_analytics_soc,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.is_analytics_soc AND p.is_new_employment)
        AS certified_h1b_analytics_soc_new_employment,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.wage_level = 'I')   AS wage_level_i,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.wage_level = 'II')  AS wage_level_ii,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.wage_level = 'III') AS wage_level_iii,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.wage_level = 'IV')  AS wage_level_iv,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND (p.wage_level IS NULL
                                              OR p.wage_level NOT IN ('I', 'II', 'III', 'IV')))
        AS wage_level_na_or_missing,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.offered_annual_wage)
        FILTER (WHERE p.is_cert_h1b) AS median_offered_annual_wage,
    COUNT(*) FILTER (WHERE p.is_cert_h1b AND p.is_wage_unit_unconvertible)
        AS n_wage_unit_unconvertible,
    MAX(p.decision_date) FILTER (WHERE p.is_cert_h1b) AS latest_certified_decision_date,
    COALESCE(BOOL_OR(p.h1b_dependent), false) AS any_h1b_dependent,
    COALESCE(BOOL_OR(p.willful_violator), false) AS any_willful_violator
FROM periods p
GROUP BY p.employer_key, p.period, p.period_fy, p.window_start_fy, p.window_end_fy;
