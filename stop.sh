#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/run"
TAILSCALE_APP_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

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

if [[ -n "${TAILSCALE_HOSTNAME:-}" ]]; then
  if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_BIN="$(command -v tailscale)"
  elif [[ -x "$TAILSCALE_APP_BIN" ]]; then
    TAILSCALE_BIN="$TAILSCALE_APP_BIN"
  fi
  if [[ -n "${TAILSCALE_BIN:-}" ]]; then
    "$TAILSCALE_BIN" serve --https=443 off >/dev/null 2>&1 || true
    echo "Stopped the private Tailscale HTTPS route."
  fi
fi
