#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'start_server: install uv before running this command\n' >&2
  exit 1
fi

if [[ -z "${FACTORY_SIMULATOR_DATABASE_URL:-}" ]]; then
  mkdir -p "$repository/data/records"
  export FACTORY_SIMULATOR_DATABASE_URL="duckdb:///$repository/data/records/runs.duckdb"
fi

exec uv run --locked --no-sync --project "$repository" uvicorn \
  factory_simulator.api.main:app --host 127.0.0.1 --port 8000 "$@"
