#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'build_docs: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 1 ]]; then
  printf 'Usage: bash %s <empty-output-directory>\n' "$0" >&2
  exit 2
fi

output_directory="$1"
if [[ "$output_directory" != /* ]]; then
  output_directory="$PWD/$output_directory"
fi

if [[ -e "$output_directory" ]]; then
  if [[ ! -d "$output_directory" ]] \
    || [[ -n "$(find "$output_directory" -mindepth 1 -print -quit)" ]]; then
    printf 'build_docs: output directory must be empty: %s\n' "$output_directory" >&2
    exit 1
  fi
else
  mkdir -p "$output_directory"
fi

build_directory="$(mktemp -d "${TMPDIR:-/tmp}/factory-simulator-docs.XXXXXX")"
trap 'rm -rf "$build_directory"' EXIT

uv run --locked --group docs --no-sync mkdocs build --strict \
  --config-file "$repository/mkdocs.development.yml" \
  --site-dir "$build_directory/development"
uv run --locked --group docs --no-sync mkdocs build --strict \
  --config-file "$repository/mkdocs.hub.yml" \
  --site-dir "$build_directory/documentation"

cp -R "$build_directory/development/." "$output_directory/"
mkdir -p "$output_directory/documentation"
cp -R "$build_directory/documentation/." "$output_directory/documentation/"
