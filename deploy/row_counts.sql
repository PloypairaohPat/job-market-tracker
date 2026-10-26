-- Row counts printed by scripts/windows/export_db.ps1 (laptop) and
-- deploy/import_db.sh (server), so the two can be compared line by line.
select name || ': ' || value
from (values
    (1, 'jobs', (select count(*) from jobs)::text),
    (2, 'job_snapshots', (select count(*) from job_snapshots)::text),
    (3, 'ingestion_runs', (select count(*) from ingestion_runs)::text),
    (4, 'latest snapshot_date', coalesce((select max(snapshot_date) from job_snapshots)::text, 'none'))
) as t (ord, name, value)
order by ord;
