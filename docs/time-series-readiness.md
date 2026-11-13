# Time-series readiness: what the snapshot data can and can't support

A methods note. It describes how the snapshot data is collected, what that means for any question asked over time, which view answers which question, and the checks to run on real data before trusting a trend. It contains no finding and no real number.

## How a snapshot is made

Each daily run searches both APIs and stores every page it fetches in `raw_responses`. Every posting on those pages gets one `job_snapshots` row for that UTC day. So a snapshot is a record of **what the search returned that day**, which differs from what was posted that day in three ways.

### 1. The search window

Each Adzuna query stops after 5 pages of 50 results, and USAJobs queries after their page limit. When a query matches more postings than the window holds, the rest are not seen that day. Which postings fall inside the window depends on the API's sort order (`ADZUNA_SORT_BY`, [daily-operation.md](daily-operation.md)). A posting can therefore drop out of the window and come back while it stays posted.

`v_search_window_coverage` measures this per query and day: results captured, the total the API reported, and the share captured. A share below 100% means every snapshot-based measure for that query and day describes a slice of the market.

`python -m src.doctor` (check 11, "search window") prints the latest fetch day's share per query, and warns when any query captured under 50% of its total. The 50% line is a convention for the warning, not a validity threshold (a parked decision in [dev-log/portfolio-readiness-progress.md](dev-log/portfolio-readiness-progress.md)).

### 2. Missed days

A day with no run has no snapshot, and it can never be backfilled: the APIs only answer for today. A job that appeared or disappeared on a missed day is first or last seen on a neighbouring day instead. `v_ingestion_daily` lists the days that have snapshots per source; a missing day is a gap in that view, never a zero row.

### 3. Changes to the instrument

Anything that changes what the search returns starts a new sample: a change of query list, page limit or sort order. Record the date of each change. Series on either side of it are not directly comparable. `raw_responses.params` records the query and, when set, the sort order of every stored page; `ingestion_runs.params` records the run's settings.

## The two honesty flags

`v_job_observation_spans` gives each analysis-population job its first and last snapshot date and two flags:

- **`entry_is_exact`** is true when the source has a snapshot on the day before the job's first sighting. Then the job really entered the window that day. It is false on the series' first day (everything already listed looks new) and after a missed day.
- **`exit_state`** is `still_listed` when the job was seen on the source's latest snapshot day, `exit_exact` when the source has a snapshot the next day and the job isn't in it, and `exit_in_gap` when the next day has no snapshot.

Even an exact exit means "left the search window that day", not "was taken down". `jobs.removed_at` is reserved and never set for that reason.

## Which view answers which question

| Question | View | What to keep in mind |
|---|---|---|
| Is data arriving every day? | `v_ingestion_daily`, `v_ingestion_runs` | A gap is a missed day; `n_runs` is 0 before the run log existed |
| How much of each query does the window capture? | `v_search_window_coverage` | Per query and day; can change with the sort order |
| How many postings did each day's search return, and how many were new or gone? | `v_daily_market_flow` | Read `prev_day_has_snapshot`: arrivals from a missed day land on the next one |
| How long does a posting stay in the search results? | `v_job_observation_spans` | Use only spans with `entry_is_exact` and `exit_state = 'exit_exact'`, and say "in the search results", not "posted" |
| Did a posting's salary change while listed? | `job_snapshots` (`salary_min`, `salary_max` per day) | Only across days the job was seen; Adzuna's predicted salaries can change without the employer changing anything |

## Checks to run on real data before trusting any trend

Run these in `psql` (or a Metabase native query) against the real database. Each has an expected shape, not an expected number.

**1. Which days have snapshots, and where the gaps are.**

```sql
SELECT source, snapshot_date, distinct_jobs, new_jobs, n_runs
FROM v_ingestion_daily
ORDER BY source, snapshot_date;
```

List the missing days per source. A trend that spans a gap needs the gap shown on its chart.

**2. How much of each query the window captures, and whether that is stable.**

```sql
SELECT source, query,
       COUNT(*)                 AS days,
       MIN(pct_captured)        AS min_pct,
       MAX(pct_captured)        AS max_pct,
       ROUND(AVG(pct_captured), 1) AS avg_pct
FROM v_search_window_coverage
GROUP BY source, query
ORDER BY source, query;
```

A query whose share is far below 100% describes a slice; one whose share moves a lot from day to day makes its daily flow move with it.

**3. Days a query was run twice, or only partly.**

```sql
SELECT source, fetch_date, query, n_responses, pages_stored, results_captured, api_total
FROM v_search_window_coverage
WHERE n_responses > pages_stored
   OR (pages_stored < 5 AND results_captured < api_total)
ORDER BY fetch_date, source, query;
```

**4. How many spans have exact edges.**

```sql
SELECT market, entry_is_exact, exit_state, COUNT(*) AS jobs
FROM v_job_observation_spans
GROUP BY market, entry_is_exact, exit_state
ORDER BY market, entry_is_exact, exit_state;
```

Only the `entry_is_exact = true` and `exit_state = 'exit_exact'` group supports a duration. If it is small, there is no duration question to answer yet.

**5. How often jobs leave the window and come back.**

```sql
SELECT market,
       COUNT(*) FILTER (WHERE days_seen < source_days_in_span) AS with_gaps,
       COUNT(*)                                                AS jobs
FROM v_job_observation_spans
GROUP BY market;
```

Many jobs with gaps means the window, not the market, drives day-to-day presence: treat daily first-seen and last-seen counts with care.

**6. The first day of the series and each instrument change.**

```sql
SELECT source, MIN(fetched_at) AS first_fetch,
       COUNT(DISTINCT params->>'sort_by') AS sort_orders_used
FROM raw_responses
GROUP BY source;
```

Exclude the first snapshot day from any "new postings" count, and split any series at a sort-order change.

## Minimum history for each kind of question

These are rules of method, set before looking at the data.

| Kind of question | Minimum history | Why |
|---|---|---|
| Daily volume (postings returned per day) | a few weeks with no gaps | enough days to see weekday effects before calling anything a change |
| New postings per day | the same, excluding the first snapshot day and every day after a gap | the first day counts everything already listed; a post-gap day absorbs the missed day's arrivals |
| Time in the search results | longer than the durations being measured, plus the spans' exact-edge filter | a span can only be measured when both its edges fall inside the series, so short histories only see short spans (right-censoring) |
| Month-over-month comparison | at least two full calendar months under one instrument (same queries, page limit and sort order) | a partial month or an instrument change makes the months different samples |
| Salary changes during a listing | as for time in the results, on employer-disclosed salaries only | Adzuna's predicted salaries can move without any employer change |
| Anything seasonal | at least a full year | one occurrence of a season can't separate it from a trend |

The project's own targets (90+ days of snapshots, 60+ days of daily ingestion; [daily-operation.md](daily-operation.md)) are the point at which the first two rows become answerable, not a guarantee that any trend will be.
