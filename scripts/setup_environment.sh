#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'setup_environment: install uv before running this command\n' >&2
  exit 1
fi

usage() {
  printf 'Usage: bash %s [--development] [--docs]\n' "$0" >&2
}

development=false
documentation=false
while (($#)); do
  case "$1" in
    --development)
      development=true
      shift
      ;;
    --docs)
      documentation=true
      shift
      ;;
    *)
      printf 'setup_environment: unknown argument: %s\n' "$1" >&2
      usage
      exit 2
      ;;
  esac
done

# An empty array expands with the form ${array[@]+"${array[@]}"}, so `set -u` holds
# on Bash 3.2.
groups=()
if [[ "$development" == true ]]; then
  groups+=(--group dev)
fi
if [[ "$documentation" == true ]]; then
  groups+=(--group docs)
fi

uv --version
uv sync --locked --no-default-groups --project "$repository" --python 3.14 \
  ${groups[@]+"${groups[@]}"}
