-- v_matched_employer_lca_wages
--
-- The offered annual wage on analytics-SOC H-1B LCA FILINGS by employers that
-- post in each market, for Phase 5 report 3. One row per market, zeros and
-- NULLs included, so a market without matched filings still has a row.
--
-- It describes FILINGS, never what postings pay: an LCA states the wage an
-- employer offered on a filing, and an LCA is not an approval or a hire. The
-- distribution is pooled over filings, so it is dominated by the largest
-- filers (staffing firms included); n_employers is beside it for that reason.
-- See src/visa/README.md, "What this can't tell you".
--
-- Filings counted: case_status = 'Certified' AND visa_class = 'H-1B', an
-- analytics SOC code, fiscal_year in the last-3-FY window anchored on the
-- latest loaded FY, filed by an employer_key that appears among the market's
-- postings (companies.normalized_name). The SOC list, the certified rule, the
-- window and the wage annualization repeat v_employer_sponsorship.sql exactly
-- (a test keeps the copied blocks identical; edit both together):
--   15-2051 Data Scientists (incl. .01 Business Intelligence Analysts)
--   15-2041 Statisticians
--   15-2031 Operations Research Analysts
--   13-1161 Market Research Analysts and Marketing Specialists
--   15-1211 Computer Systems Analysts
--   13-1111 Management Analysts
--   15-1243 Database Architects
--   13-2051 Financial and Investment Analysts
--
--   n_filings              matched employers' certified analytics-SOC H-1B
--                          filings in the window (equals the sum of their
--                          v_employer_sponsorship.certified_h1b_analytics_soc)
--   n_filings_with_wage    of those, with a wage unit that annualizes
--   n_employers            employers behind n_filings
--   n_employers_with_wage  employers behind n_filings_with_wage
--   largest_employer_n_filings  the most n_filings any one employer accounts
--                          for: how far a single large filer drives the pool
--                          (a count only; the employer isn't named)
--   p25 / median / p75_offered_annual_wage  over n_filings_with_wage
-- Robustness checks (appended last; the columns above are unchanged), to see
-- how far the pooled median is the largest filers' median:
--   median_excl_largest_filer     the same pooled median with the single
--                                 largest filer's filings removed (largest by
--                                 n filings, ties to the first employer_key);
--                                 NULL when fewer than 2 employers
--   n_filings_excl_largest_filer  the filings with a wage behind it (0 if none)
--   median_of_employer_medians    each employer's median offered wage over its
--                                 filings with a wage, then the median of those
--   n_employers_for_median_of_medians  the employers behind it (0 if none)
-- Aggregate only: no filing-level columns.

CREATE OR REPLACE VIEW v_matched_employer_lca_wages AS
WITH analytics_soc(soc_prefix) AS (
    VALUES ('15-2051'), ('15-2041'), ('15-2031'), ('13-1161'),
           ('15-1211'), ('13-1111'), ('15-1243'), ('13-2051')
),
population AS (
    SELECT
        CASE WHEN j.source = 'adzuna' THEN 'commercial' ELSE 'federal' END AS market,
        c.normalized_name AS employer_key
    FROM jobs j
    LEFT JOIN companies c ON c.id = j.company_id
    WHERE j.source = 'adzuna'
       OR (j.source = 'usajobs' AND j.in_scope)
),
markets AS (
    SELECT DISTINCT market FROM population
),
employers AS (
    SELECT DISTINCT market, employer_key FROM population WHERE employer_key IS NOT NULL
),
fy_window AS (
    SELECT MAX(fiscal_year) AS end_fy FROM lca_cases
),
filings AS (
    SELECT
        c.employer_key,
        CASE LOWER(TRIM(c.wage_unit_of_pay))
            WHEN 'hour'      THEN c.wage_rate_of_pay_from * 2080
            WHEN 'week'      THEN c.wage_rate_of_pay_from * 52
            WHEN 'bi-weekly' THEN c.wage_rate_of_pay_from * 26
            WHEN 'month'     THEN c.wage_rate_of_pay_from * 12
            WHEN 'year'      THEN c.wage_rate_of_pay_from
        END AS offered_annual_wage
    FROM lca_cases c
    CROSS JOIN fy_window w
    WHERE c.employer_key IS NOT NULL
      AND c.case_status = 'Certified'
      AND c.visa_class = 'H-1B'
      AND LEFT(c.soc_code, 7) IN (SELECT soc_prefix FROM analytics_soc)
      AND c.fiscal_year BETWEEN w.end_fy - 2 AND w.end_fy
),
matched AS (
    SELECT e.market, f.employer_key, f.offered_annual_wage
    FROM employers e
    JOIN filings f ON f.employer_key = e.employer_key
),
per_employer AS (
    SELECT market, employer_key, COUNT(*) AS n
    FROM matched
    GROUP BY market, employer_key
),
largest AS (
    SELECT market, MAX(n) AS largest_employer_n_filings
    FROM per_employer
    GROUP BY market
),
largest_filer AS (
    SELECT DISTINCT ON (market) market, employer_key
    FROM per_employer
    ORDER BY market, n DESC, employer_key
),
excl_largest AS (
    SELECT
        x.market,
        COUNT(x.offered_annual_wage) AS n_filings_excl_largest_filer,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY x.offered_annual_wage)
            AS median_excl_largest_filer
    FROM matched x
    JOIN largest_filer lf ON lf.market = x.market AND x.employer_key <> lf.employer_key
    GROUP BY x.market
),
employer_medians AS (
    SELECT
        market,
        employer_key,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY offered_annual_wage) AS employer_median
    FROM matched
    WHERE offered_annual_wage IS NOT NULL
    GROUP BY market, employer_key
),
median_of_medians AS (
    SELECT
        market,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY employer_median)
            AS median_of_employer_medians,
        COUNT(*) AS n_employers_for_median_of_medians
    FROM employer_medians
    GROUP BY market
)
SELECT
    m.market,
    COUNT(x.employer_key) AS n_filings,
    COUNT(x.offered_annual_wage) AS n_filings_with_wage,
    COUNT(DISTINCT x.employer_key) AS n_employers,
    COUNT(DISTINCT x.employer_key) FILTER (WHERE x.offered_annual_wage IS NOT NULL)
        AS n_employers_with_wage,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY x.offered_annual_wage) AS p25_offered_annual_wage,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY x.offered_annual_wage) AS median_offered_annual_wage,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY x.offered_annual_wage) AS p75_offered_annual_wage,
    COALESCE(MAX(lg.largest_employer_n_filings), 0) AS largest_employer_n_filings,
    MAX(el.median_excl_largest_filer) AS median_excl_largest_filer,
    COALESCE(MAX(el.n_filings_excl_largest_filer), 0) AS n_filings_excl_largest_filer,
    MAX(mm.median_of_employer_medians) AS median_of_employer_medians,
    COALESCE(MAX(mm.n_employers_for_median_of_medians), 0) AS n_employers_for_median_of_medians
FROM markets m
LEFT JOIN matched x ON x.market = m.market
LEFT JOIN largest lg ON lg.market = m.market
LEFT JOIN excl_largest el ON el.market = m.market
LEFT JOIN median_of_medians mm ON mm.market = m.market
GROUP BY m.market
ORDER BY m.market;
