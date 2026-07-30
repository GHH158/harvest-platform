#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/run"

for service in api worker; do
  pid_file="$RUN_DIR/$service.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "Stopped $service (PID $pid)."
    else
      echo "$service was not running."
    fi
    rm -f "$pid_file"
  else
    echo "$service was not running."
  fi
done
