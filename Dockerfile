# Pipeline image: the daily runner, migrations, views, health check, reader
# role and Metabase provisioner (docs/deploy.md). The stack passes the real
# command, e.g.
#   docker compose -f deploy/docker-compose.prod.yml run --rm pipeline python -m src.pipeline.daily
#
# Layout: code in /app (on PYTHONPATH, read-only to the app user); the
# working directory is /var/lib/jobmarket, where the runner writes its
# relative logs/ and data/ (a volume in the stack). The image itself holds
# no .env, data, logs or tests (.dockerignore).
FROM python:3.12.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && install -d -o app -g app /var/lib/jobmarket

WORKDIR /app
# no dev extras. Behind a TLS-intercepting proxy, pass its CA bundle for this
# one step: docker build --secret id=extra_ca,src=<bundle.pem> . (a build
# secret: used by pip here, never stored in the image). Without it, pip uses
# the image's own CA store.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
    && pip install . \
    && rm -rf build ./*.egg-info src/*.egg-info

COPY alembic.ini ./
COPY migrations/ migrations/
COPY sql/ sql/
COPY scripts/ scripts/
COPY dashboards/ dashboards/

USER app
WORKDIR /var/lib/jobmarket
CMD ["python", "-m", "src.pipeline.health", "--help"]
