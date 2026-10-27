.PHONY: up db-migrate seed-demo ingest smoke test lint notebook views daily health bi-grant bi-up bi-provision prod-build prod-up prod-down prod-ps prod-logs prod-metabase-db prod-migrate prod-views prod-grant prod-provision prod-daily prod-health

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

bi-grant:        ## create/update the read-only metabase_reader role (SELECT on v_* views only)
	python -m src.dashboard.reader_role

bi-up:           ## start Metabase (and db) -- the opt-in "bi" compose profile
	docker compose --profile bi up -d

bi-provision:    ## build/refresh every Metabase dashboard from dashboards/ (idempotent)
	python -m src.dashboard.provision

# --- production stack (server; docs/deploy.md). Always uses the root .env. ---
PROD := docker compose -f deploy/docker-compose.prod.yml --env-file .env

prod-build:      ## build the pipeline image on the server
	$(PROD) build pipeline

prod-up:         ## start db, metabase and caddy (waits until healthy)
	$(PROD) up -d --wait db metabase caddy

prod-down:       ## stop the stack (volumes and data are kept)
	$(PROD) down

prod-ps:         ## show the stack's containers and published ports
	$(PROD) ps

prod-logs:       ## follow the logs of every service
	$(PROD) logs -f --tail=100

prod-metabase-db: ## create/update Metabase's app database on an existing db volume
	deploy/ensure_metabase_db.sh

prod-migrate:    ## alembic upgrade head, inside the pipeline image
	$(PROD) run --rm pipeline alembic -c /app/alembic.ini upgrade head

prod-views:      ## apply every SQL view, inside the pipeline image
	$(PROD) run --rm pipeline python /app/scripts/apply_views.py

prod-grant:      ## create/update the read-only metabase_reader role
	$(PROD) run --rm pipeline python -m src.dashboard.reader_role

prod-provision:  ## build/refresh the Metabase dashboards (add ARGS=--public-links)
	$(PROD) run --rm pipeline python -m src.dashboard.provision $(ARGS)

prod-daily:      ## one daily run now (normally the systemd timer runs it)
	$(PROD) run --rm pipeline python -m src.pipeline.daily $(ARGS)

prod-health:     ## is the daily clock running on the server?
	$(PROD) run --rm pipeline python -m src.pipeline.health
