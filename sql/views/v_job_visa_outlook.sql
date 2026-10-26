-- v_job_visa_outlook
--
-- One row per IN-SCOPE job: how open it looks to someone on F-1 OPT who will
-- later need H-1B sponsorship, with the evidence beside the verdict. Combines
-- three independent signals:
--   1. posting text        job_visa_signals (apply_cleaning --only visa)
--   2. employer history    v_employer_sponsorship, period = 'last_3_fy'
--                          (joined on companies.normalized_name = employer_key;
--                          near-misses go through src/visa/sponsor_match.py)
--   3. cap-exempt hint     job_visa_signals.cap_exempt_hint (name only)
-- Depends on v_employer_sponsorship, which sorts before this file, so
-- `make views` (file-name order) creates it first.
--
-- Buckets, applied IN THIS ORDER (first match wins). Thresholds are defaults
-- parked for the owner's confirmation in docs/overnight-visa-layer.md:
--   closed    restriction is citizenship or clearance, or the posting says
--             will_not_sponsor -- a "no" in the posting beats any history
--   strong    will_sponsor, OR >= 3 certified analytics-SOC H-1B LCAs with
--             new employment in the last 3 FYs, OR cap_exempt_hint = likely
--   possible  any certified H-1B LCA in the last 3 FYs
--   unknown   everything else, INCLUDING no employer match and jobs the visa
--             step hasn't classified yet (no job_visa_signals row)
-- bucket_reason names the rule that fired.
--
-- unknown is not "no": on truncated text (text_coverage = 'truncated', every
-- Adzuna posting) a sponsorship sentence may simply have been cut off.
-- Every LCA column here is an employer-level aggregate; nothing row-level
-- from lca_cases is exposed.

CREATE OR REPLACE VIEW v_job_visa_outlook AS
WITH joined AS (
    SELECT
        j.id                AS job_id,
        j.source,
        j.title,
        c.canonical_name    AS company,
        c.normalized_name   AS employer_key,
        l.metro_area,
        j.redirect_url,
        s.restriction,
        s.restriction_reason,
        s.sponsorship_stance,
        s.sponsorship_reason,
        s.opt_mentioned,
        s.text_coverage,
        s.cap_exempt_hint,
        s.cap_exempt_reason,
        (es.employer_key IS NOT NULL)                         AS employer_matched,
        es.window_start_fy                                    AS lca_window_start_fy,
        es.window_end_fy                                      AS lca_window_end_fy,
        COALESCE(es.certified_h1b_lcas, 0)                    AS certified_h1b_lcas,
        COALESCE(es.certified_h1b_new_employment, 0)          AS certified_h1b_new_employment,
        COALESCE(es.certified_h1b_analytics_soc, 0)           AS certified_h1b_analytics_soc,
        COALESCE(es.certified_h1b_analytics_soc_new_employment, 0)
                                                              AS certified_h1b_analytics_soc_new_employment,
        COALESCE(es.wage_level_i, 0)                          AS wage_level_i,
        COALESCE(es.wage_level_ii, 0)                         AS wage_level_ii,
        COALESCE(es.wage_level_iii, 0)                        AS wage_level_iii,
        COALESCE(es.wage_level_iv, 0)                         AS wage_level_iv,
        COALESCE(es.wage_level_na_or_missing, 0)              AS wage_level_na_or_missing,
        es.median_offered_annual_wage,
        es.latest_certified_decision_date,
        es.any_h1b_dependent,
        es.any_willful_violator
    FROM jobs j
    LEFT JOIN job_visa_signals s ON s.job_id = j.id
    LEFT JOIN companies c ON c.id = j.company_id
    LEFT JOIN locations l ON l.id = j.location_id
    LEFT JOIN v_employer_sponsorship es
           ON es.employer_key = c.normalized_name AND es.period = 'last_3_fy'
    WHERE j.in_scope
)
SELECT
    joined.*,
    CASE
        WHEN restriction IN ('citizenship', 'clearance')         THEN 'closed'
        WHEN sponsorship_stance = 'will_not_sponsor'             THEN 'closed'
        WHEN sponsorship_stance = 'will_sponsor'                 THEN 'strong'
        WHEN certified_h1b_analytics_soc_new_employment >= 3     THEN 'strong'
        WHEN cap_exempt_hint = 'likely'                          THEN 'strong'
        WHEN certified_h1b_lcas > 0                              THEN 'possible'
        ELSE 'unknown'
    END AS bucket,
    CASE
        WHEN restriction IN ('citizenship', 'clearance')         THEN 'posting restriction: ' || restriction
        WHEN sponsorship_stance = 'will_not_sponsor'             THEN 'posting: will not sponsor'
        WHEN sponsorship_stance = 'will_sponsor'                 THEN 'posting: will sponsor'
        WHEN certified_h1b_analytics_soc_new_employment >= 3     THEN 'employer: >=3 analytics-SOC new-employment H-1B LCAs in last 3 FYs'
        WHEN cap_exempt_hint = 'likely'                          THEN 'cap-exempt hint (name)'
        WHEN certified_h1b_lcas > 0                              THEN 'employer: certified H-1B LCA(s) in last 3 FYs'
        WHEN restriction IS NULL                                 THEN 'not yet classified (run the visa step)'
        WHEN NOT employer_matched                                THEN 'no signal; no LCA employer match'
        ELSE 'no signal; employer matched but no certified H-1B LCAs in last 3 FYs'
    END AS bucket_reason
FROM joined;
