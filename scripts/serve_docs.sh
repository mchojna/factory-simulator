#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'serve_docs: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 1 ]]; then
  printf 'Usage: bash %s <development>\n' "$0" >&2
  exit 2
fi

case "$1" in
  development)
    configuration="$repository/mkdocs.development.yml"
    port=8001
    ;;
  *)
    printf 'serve_docs: collection must be development\n' >&2
    printf 'Usage: bash %s <development>\n' "$0" >&2
    exit 2
    ;;
esac

cd "$repository"
exec uv run --locked --group docs --no-sync mkdocs serve \
  --config-file "$configuration" \
  --dev-addr "127.0.0.1:${port}"
