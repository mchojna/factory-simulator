#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'export_transport: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 2 ]]; then
  printf 'Usage: bash %s <stopped-database.duckdb> <new-transport.zip>\n' "$0" >&2
  exit 2
fi

if [[ ! -f "$1" ]]; then
  printf 'export_transport: stopped database not found: %s\n' "$1" >&2
  exit 1
fi

cd "$repository"
exec uv run --locked --no-sync python -m factory_simulator.api.record.transport \
  "$1" "$2"
