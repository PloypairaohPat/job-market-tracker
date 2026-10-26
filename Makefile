.PHONY: up db-migrate seed-demo ingest smoke test lint notebook views daily health

up:              ## start Postgres
	docker compose up -d

db-migrate:      ## apply schema migrations
	alembic upgrade head

seed-demo:       ## load synthetic demo data (no API key needed)
	python scripts/seed_demo_data.py

smoke:           ## one live API call to verify Adzuna credentials
	python scripts/smoke_adzuna.py

ingest:          ## full Adzuna ingestion (budgeted)
	python -m src.ingestion.ingest_adzuna

test:            ## run all tests (integration tests need TEST_DATABASE_URL)
	pytest

lint:            ## lint + format check
	ruff check . && ruff format --check .

notebook:        ## open the exploration notebook
	jupyter lab notebooks/01_initial_exploration.ipynb

extract-skills:  ## sync taxonomy + extract job skills
	python -m src.cleaning.extract_skills

apply-cleaning:  ## seniority, salary quality, remote, metro, company normalization
	python -m src.cleaning.apply_cleaning

views:           ## apply every sql/views/*.sql (file-name order, one transaction)
	python scripts/apply_views.py

daily:           ## the daily pipeline: adzuna (budget-guarded), usajobs, cleaning, skills
	python -m src.pipeline.daily

health:          ## is the daily clock running? (read-only; exit 1 on any FAIL)
	python -m src.pipeline.health
