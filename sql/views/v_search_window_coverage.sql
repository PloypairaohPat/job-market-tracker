-- v_search_window_coverage
--
-- How much of each search's result set the stored pages captured, one row
-- per (source, UTC fetch date, query). Built on raw_responses only, so it
-- covers every day a page was stored, before and after the run log existed.
--
-- Why it matters: each daily search stops at a fixed window (Adzuna: at most
-- 5 pages of 50 per query; USAJobs: at most its page limit), and the APIs
-- report how many results the query matched in total. A posting that falls
-- outside the window on a given day is simply not in that day's snapshot.
-- So "seen" in job_snapshots means "returned inside that day's search
-- window", not "live on the employer's site". When pct_captured is below
-- 100, every snapshot-based measure for that query and day (first and last
-- seen, days seen, daily flow; v_job_observation_spans, v_daily_market_flow)
-- describes the captured slice only, and a job missing from a day may have
-- moved outside the window rather than been taken down. Which slice the
-- window holds depends on the API's sort order (ADZUNA_SORT_BY,
-- docs/daily-operation.md).
--
-- Sources (both verified against tests/fixtures/ and the ingestion code):
--   adzuna   query = params->>'what'; page = params->>'page';
--            total = response->>'count'; results = response->'results'
--   usajobs  query = params->>'Keyword', or 'series:<code>' for an
--            occupational-series search (params->>'JobCategoryCode'), the
--            same labels the ingester logs; page = params->>'Page';
--            total = response->'SearchResult'->>'SearchResultCountAll';
--            results = response->'SearchResult'->'SearchResultItems'
--
-- Columns:
--   source, fetch_date   fetch_date is the UTC date of fetched_at
--   query                as above
--   n_responses          raw_responses rows stored (> pages_stored when a
--                        page was fetched twice that day, e.g. a retried run)
--   pages_stored         distinct page numbers stored
--   results_captured     results on those pages, counting each page once
--                        (its latest fetch that day)
--   api_total            the largest total the API reported that day (it
--                        can drift between pages of one run)
--   pct_captured         100 * results_captured / api_total, one decimal;
--                        NULL when api_total is missing or 0. It can exceed
--                        100 if the total shrank during the run.

CREATE OR REPLACE VIEW v_search_window_coverage AS
WITH pages AS (
    SELECT
        r.id,
        r.source,
        (r.fetched_at AT TIME ZONE 'UTC')::date AS fetch_date,
        r.fetched_at,
        CASE r.source
            WHEN 'adzuna' THEN r.params->>'what'
            ELSE COALESCE(r.params->>'Keyword', 'series:' || (r.params->>'JobCategoryCode'))
        END AS query,
        CASE r.source
            WHEN 'adzuna' THEN r.params->>'page'
            ELSE r.params->>'Page'
        END AS page,
        CASE r.source
            WHEN 'adzuna' THEN (r.response->>'count')::numeric::bigint
            ELSE (r.response->'SearchResult'->>'SearchResultCountAll')::numeric::bigint
        END AS api_total,
        CASE r.source
            WHEN 'adzuna' THEN COALESCE(jsonb_array_length(r.response->'results'), 0)
            ELSE COALESCE(jsonb_array_length(r.response->'SearchResult'->'SearchResultItems'), 0)
        END AS n_results
    FROM raw_responses r
    WHERE r.source IN ('adzuna', 'usajobs')
),
latest_page AS (
    SELECT DISTINCT ON (source, fetch_date, query, page)
        source, fetch_date, query, page, n_results
    FROM pages
    ORDER BY source, fetch_date, query, page, fetched_at DESC, id DESC
),
captured AS (
    SELECT source, fetch_date, query,
           COUNT(*)        AS pages_stored,
           SUM(n_results)  AS results_captured
    FROM latest_page
    GROUP BY source, fetch_date, query
),
reported AS (
    SELECT source, fetch_date, query,
           COUNT(*)        AS n_responses,
           MAX(api_total)  AS api_total
    FROM pages
    GROUP BY source, fetch_date, query
)
SELECT
    c.source,
    c.fetch_date,
    c.query,
    rp.n_responses,
    c.pages_stored,
    c.results_captured::bigint AS results_captured,
    rp.api_total,
    ROUND(100.0 * c.results_captured / NULLIF(rp.api_total, 0), 1) AS pct_captured
FROM captured c
JOIN reported rp
  ON rp.source = c.source AND rp.fetch_date = c.fetch_date
 AND rp.query IS NOT DISTINCT FROM c.query;
