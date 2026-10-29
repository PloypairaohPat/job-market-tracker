-- v_lca_monthly
--
-- LCA decisions per calendar month, per loaded fiscal year: the month-level
-- companion of v_lca_coverage (which sorts before this file). Report 3's
-- Methods reads both to show how complete each fiscal year in its filing
-- window is, and to flag a month with unusually few decisions.
--
-- One row per (fiscal_year, month) that has at least one decision:
--   fiscal_year  the --fiscal-year the case was loaded under
--   month        the first day of the calendar month of decision_date
--   n_cases      cases decided in that month (one row per case_number)
-- A month with no decisions has no row: v_lca_coverage's
-- n_months_with_decisions counts the rows here. Cases with no decision_date
-- are left out. Aggregate only: no case_number or employer column.

CREATE OR REPLACE VIEW v_lca_monthly AS
SELECT
    fiscal_year,
    date_trunc('month', decision_date)::date AS month,
    COUNT(*) AS n_cases
FROM lca_cases
WHERE decision_date IS NOT NULL
GROUP BY fiscal_year, date_trunc('month', decision_date)::date
ORDER BY fiscal_year, month;
