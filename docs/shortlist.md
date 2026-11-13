# The private shortlist

`python -m src.shortlist` answers one question for the owner's own job search: which postings first seen in the last few days fit a profile? It reads the database (`DATABASE_URL`), calls no API, and writes a Markdown file and a CSV.

**The output is private.** It names postings and employers, like the Visa outlook dashboard. It goes to `data\shortlist\` (gitignored) and is never committed. The command refuses an output directory inside the repo that git tracks or doesn't ignore.

Commands below are for Windows PowerShell with `uv`, run from the repo root, one per line.

## First time: a profile

The profile is `shortlist.toml` in the repo root (gitignored). Start from the example, which lists every option with its default:

```powershell
Copy-Item "shortlist.example.toml" "shortlist.toml"
notepad "shortlist.toml"
```

Uncomment and edit the options you want. A misspelled option, metro, seniority level, visa bucket or skill name stops the command with a message naming it, so a typo can't silently empty the list.

## Run it

```powershell
uv run python -m src.shortlist
```

It prints the number of entries and the path, for example `data\shortlist\shortlist-2026-03-09.md`, with a `.csv` beside it. A second run on the same UTC day overwrites that day's files. `make shortlist` runs the same command where `make` is available.

Options: `--profile PATH` (default `shortlist.toml`), `--out DIR` (default `data\shortlist`), `--database-url URL` (default `DATABASE_URL`).

## What the filters do

| Option | Effect |
|---|---|
| `lookback_days` (7) | postings whose `jobs.first_seen_at` is within the last N days |
| `title_include`, `title_exclude` | case-insensitive substrings of the title: keep if any include matches, drop if any exclude matches |
| `skills_any`, `skills_all` | `job_skills` matches at confidence >= 0.8, by taxonomy name (`src/cleaning/data/skills.json`, any case) |
| `metros`, `include_remote` (true) | tracked metros from `src/cleaning/metro.py`; with metros set, `include_remote` also keeps remote postings anywhere; with no metros, `include_remote = false` drops remote postings |
| `seniority`, `include_no_seniority_signal` (true) | title-based levels (`junior`, `mid`, `senior`, `lead`); postings whose title has no seniority signal are kept and labelled "no title signal" unless you turn that off |
| `min_salary`, `min_salary_uses_predicted` (false) | the top of the posted range, annualized (hour x 2080, month x 12), compared only for employer-disclosed salaries that passed the salary quality check. Postings without a salary are kept. Adzuna's predicted salaries are shown, labelled "Adzuna's estimate", and only exclude when you opt in |
| `visa_buckets` | `strong`, `possible`, `unknown`, `closed` from `v_job_visa_outlook` ([docs/dashboard.md](dashboard.md)); `unknown` is not "no" |

The population is the analysis population: every commercial (Adzuna) posting and in-scope federal (USAJobs) postings.

## Reading the output

- **One entry per employer and normalized title.** Reposts of the same role (several cities, or the same job posted again) are collapsed: the entry lists every location and the number of postings, and its link, salary and first-seen date come from the newest posting. Entries are newest first.
- **Salary** always carries its basis: employer-disclosed, or Adzuna's estimate, plus any quality flag.
- **Skills** are the matches at confidence >= 0.8 across the collapsed postings. Commercial descriptions are truncated by the API, so a missing skill may have been cut off; the file says this once at the top.
- **Visa outlook** is the bucket from `v_job_visa_outlook`. When collapsed postings differ, every bucket is listed.
- On a database whose name contains `demo` or `test` the file says "Synthetic demo data, not real postings."
