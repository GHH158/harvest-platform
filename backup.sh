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
if command -v brew >/dev/null 2>&1 && brew --prefix postgresql@17 >/dev/null 2>&1; then
  PG_BIN="$(brew --prefix postgresql@17)/bin"
elif [[ -x "$ROOT_DIR/.local/Postgres.app/Contents/Versions/17/bin/pg_dump" ]]; then
  PG_BIN="$ROOT_DIR/.local/Postgres.app/Contents/Versions/17/bin"
else
  echo "PostgreSQL 17 command-line tools are unavailable." >&2
  exit 1
fi
export PATH="$PG_BIN:$PATH"
mkdir -p "$BACKUP_DIR"
output="$BACKUP_DIR/harvest-$(date +%Y%m%d-%H%M%S).sql.gz"
# §7.4 / §14.3: the private journal is never backed up. --exclude-table-data (not
# --exclude-table) so a restored database still HAS the tables, just empty, and the app
# does not fail on a missing relation. The cost is deliberate and written down in §7.4:
# this content has no copy anywhere — deleting it is permanent, and a dead disk takes it
# with it. It is also the one thing here that should not be lying around in a dump.
pg_dump "$PG_DATABASE_URL" \
  --exclude-table-data=journal_entry \
  --exclude-table-data=journal_reply \
  | gzip >"$output"
echo "Backup: $output"
echo "Excluded (§14.3): journal_entry, journal_reply — no copy is kept anywhere."
du -h "$output" | awk '{print "Size: " $1}'
