-- Top employers by normalized name (the grouping key); display name = most frequent raw name.
-- Postings with no company are excluded (counted in n_jobs_without_company).
SELECT
    employer_key,
    MODE() WITHIN GROUP (ORDER BY employer_name)                   AS employer,
    COUNT(*)                                                       AS n_jobs,
    STRING_AGG(DISTINCT market, ', ')                              AS markets,
    (SELECT COUNT(*) FROM v_market_jobs WHERE employer_key IS NULL) AS n_jobs_without_company
FROM v_market_jobs
WHERE employer_key IS NOT NULL
GROUP BY employer_key
ORDER BY n_jobs DESC, employer_key
LIMIT 15;
