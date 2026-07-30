#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
BACKUP_DIR="$ROOT_DIR/backups"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env." >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
PG_DATABASE_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required for PostgreSQL 17." >&2
  exit 1
fi
export PATH="$(brew --prefix postgresql@17)/bin:$PATH"
mkdir -p "$BACKUP_DIR"
output="$BACKUP_DIR/harvest-$(date +%Y%m%d-%H%M%S).sql.gz"
pg_dump "$PG_DATABASE_URL" | gzip >"$output"
echo "Backup: $output"
du -h "$output" | awk '{print "Size: " $1}'
