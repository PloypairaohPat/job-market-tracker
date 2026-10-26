-- Top federal (USAJobs, in-scope) skills: rate with its count and the market's job count.
SELECT name, category, pct_of_jobs, n_jobs_tagged, market_n_jobs
FROM v_skill_top_by_source
WHERE market = 'federal'
ORDER BY n_jobs_tagged DESC, name
LIMIT 15;
