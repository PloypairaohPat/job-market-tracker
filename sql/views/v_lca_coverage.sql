-- v_lca_coverage
--
-- What lca_cases holds for each fiscal year, so the owner can check after
-- loading that every quarter of a fiscal year is in. One row per
-- fiscal_year loaded (the --fiscal-year given to src/visa/lca_loader.py):
--   fiscal_year              federal FY: 1 Oct of FY-1 to 30 Sep of FY
--   n_cases                  cases stored (one row per case_number)
--   min_decision_date        earliest DECISION_DATE
--   max_decision_date        latest DECISION_DATE
--   n_months_with_decisions  calendar months with at least one decision:
--                            12 for a complete FY, fewer for a partial one
--                            (9 for a current FY loaded to June)
--
-- Some fiscal years' quarterly files hold one quarter each and others are
-- cumulative, so a missing quarterly file shows here as fewer months or a
-- late min_decision_date, never as an error. Cases with no decision_date
-- count in n_cases but not in the dates or months. The 3-FY window of
-- v_employer_sponsorship is uneven while the current FY is partial.
-- Aggregate only: no case_number or employer column.

CREATE OR REPLACE VIEW v_lca_coverage AS
SELECT
    fiscal_year,
    COUNT(*) AS n_cases,
    MIN(decision_date) AS min_decision_date,
    MAX(decision_date) AS max_decision_date,
    COUNT(DISTINCT date_trunc('month', decision_date)) AS n_months_with_decisions
FROM lca_cases
GROUP BY fiscal_year;
