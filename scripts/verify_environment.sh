#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'verify_environment: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 0 ]]; then
  printf 'Usage: bash %s\n' "$0" >&2
  exit 2
fi

uv --version
if ! uv lock --check --project "$repository"; then
  printf 'verify_environment: uv.lock does not match pyproject.toml; %s\n' \
    'update and commit the lock intentionally' >&2
  exit 1
fi

uv run --locked --no-sync --project "$repository" python -c '
import factory_simulator.api.main
import factory_simulator.benchmark.client
import factory_simulator.benchmark.optimizers.no_decisions

print("Base application and optimizer imports passed without provider credentials.")
'
