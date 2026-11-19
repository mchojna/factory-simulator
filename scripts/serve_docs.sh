#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'serve_docs: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 0 ]]; then
  printf 'Usage: bash %s\n' "$0" >&2
  exit 2
fi

cd "$repository"
exec uv run --locked --group docs --no-sync mkdocs serve \
  --config-file "$repository/mkdocs.yml" \
  --dev-addr "127.0.0.1:8001"
