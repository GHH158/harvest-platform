#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
RUN_DIR="$ROOT_DIR/run"
TAILSCALE_APP_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env. Copy .env.example and fill DATABASE_URL first." >&2
  exit 1
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing .venv. Create it with Python 3.12 and install this project first." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a
PG_DATABASE_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

if command -v brew >/dev/null 2>&1 && brew --prefix postgresql@17 >/dev/null 2>&1; then
  PG_BIN="$(brew --prefix postgresql@17)/bin"
  PG_DATA_DIR=""
elif [[ -x "$ROOT_DIR/.local/Postgres.app/Contents/Versions/17/bin/pg_ctl" ]]; then
  PG_BIN="$ROOT_DIR/.local/Postgres.app/Contents/Versions/17/bin"
  PG_DATA_DIR="$ROOT_DIR/.local/pgdata"
else
  echo "PostgreSQL 17 is unavailable. Install Homebrew PostgreSQL or place Postgres.app in .local/." >&2
  exit 1
fi
export PATH="$PG_BIN:$PATH"

if ! pg_isready -d "$PG_DATABASE_URL" >/dev/null 2>&1; then
  if [[ -n "$PG_DATA_DIR" ]]; then
    pg_ctl -D "$PG_DATA_DIR" -l "$ROOT_DIR/.local/postgresql.log" start
  else
    brew services start postgresql@17
  fi
fi
until pg_isready -d "$PG_DATABASE_URL" >/dev/null 2>&1; do sleep 1; done

mkdir -p "$RUN_DIR"
DB_NAME="${PG_DATABASE_URL##*/}"
DB_ADMIN_URL="${PG_DATABASE_URL%/*}/postgres"
if ! psql "$DB_ADMIN_URL" -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
  createdb --maintenance-db="$DB_ADMIN_URL" "$DB_NAME"
fi
"$VENV_PYTHON" -m app.db

if [[ -f "$RUN_DIR/api.pid" ]] && kill -0 "$(cat "$RUN_DIR/api.pid")" 2>/dev/null; then
  echo "API is already running (PID $(cat "$RUN_DIR/api.pid"))." >&2
  exit 1
fi

cd "$ROOT_DIR/backend"
nohup "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >"$RUN_DIR/api.log" 2>&1 &
echo $! >"$RUN_DIR/api.pid"
nohup "$VENV_PYTHON" -m app.worker >"$RUN_DIR/worker.log" 2>&1 &
echo $! >"$RUN_DIR/worker.pid"

if [[ -n "${TAILSCALE_HOSTNAME:-}" ]]; then
  if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_BIN="$(command -v tailscale)"
  elif [[ -x "$TAILSCALE_APP_BIN" ]]; then
    TAILSCALE_BIN="$TAILSCALE_APP_BIN"
  else
    echo "TAILSCALE_HOSTNAME is set but the Tailscale CLI is unavailable." >&2
    exit 1
  fi
  "$TAILSCALE_BIN" serve --bg --https=443 http://127.0.0.1:8000
  echo "Harvest ingest: https://$TAILSCALE_HOSTNAME/ingest-web"
else
  echo "Harvest ingest: http://127.0.0.1:8000/ingest-web"
fi
echo "API and worker logs: $RUN_DIR"
