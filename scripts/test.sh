#!/usr/bin/env bash
# Run the E2E suite. Default: throw-away SQLite (zero external dependency).
# PostgreSQL path: export DATABASE_URL first, see README section "运行".
#
# EVIDENCE_OUT=<path> writes a sanitised report (absolute repo paths replaced
# with "."), so a public report never leaks a local filesystem layout.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

export AUTO_CREATE_SCHEMA="${AUTO_CREATE_SCHEMA:-1}"
export SEED_DEMO_DATA="${SEED_DEMO_DATA:-0}"

if [ -z "${DATABASE_URL:-}" ]; then
  mkdir -p .data
  export DATABASE_URL="sqlite+pysqlite:///${DIR}/.data/e2e-$(date +%Y%m%d%H%M%S).sqlite3"
fi

DB_DISPLAY="$(printf '%s' "$DATABASE_URL" | sed "s|$DIR|.|g")"
echo "DATABASE_URL=${DB_DISPLAY}"

if [ -n "${EVIDENCE_OUT:-}" ]; then
  .venv/bin/python -m pytest -v --cov=app --cov-report=term-missing "$@" 2>&1 \
    | sed "s|$DIR|.|g" > "$EVIDENCE_OUT"
  tail -n 3 "$EVIDENCE_OUT"
else
  .venv/bin/python -m pytest -v --cov=app --cov-report=term-missing "$@"
fi
