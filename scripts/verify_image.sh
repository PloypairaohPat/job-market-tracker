#!/bin/sh
# Check a built pipeline image: nothing private or test-only inside, a
# non-root user, no dev tools, and the code imports and runs.
# Usage: scripts/verify_image.sh [image]   (default job-market-tracker:local)
set -eu
image="${1:-job-market-tracker:local}"
run() { docker run --rm --entrypoint "" "$image" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

listing="$(run ls -a /app)"
echo "/app contains: $(printf "%s" "$listing" | tr "\n" " ")"
for banned in .env data logs tests notebooks .git .venv; do
    printf '%s\n' "$listing" | grep -qx -- "$banned" && fail "/app/$banned is in the image"
done
found="$(run find /app /var/lib/jobmarket \( -name '.env*' -o -name '*.dump' -o -name 'tests' \) -print)"
[ -z "$found" ] || fail "unexpected files in the image: $found"

uid="$(run id -u)"
[ "$uid" != "0" ] || fail "runs as root"
echo "runs as uid $uid"

run python -c "import importlib.util as u, sys; sys.exit(any(u.find_spec(m) for m in ('pytest', 'ruff')))" \
    || fail "dev tools (pytest/ruff) are installed"
run sh -c 'touch /var/lib/jobmarket/.write-test && rm /var/lib/jobmarket/.write-test' \
    || fail "working directory /var/lib/jobmarket is not writable"
run python -c "import src.pipeline.daily, src.pipeline.health, src.dashboard.provision, src.dashboard.reader_role"
docker run --rm "$image" >/dev/null || fail "default command failed"
run alembic -c /app/alembic.ini heads
echo "image $image OK"
