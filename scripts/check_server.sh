#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository="$(cd "$script_directory/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'check_server: install uv before running this command\n' >&2
  exit 1
fi

if [[ "$#" -ne 0 ]]; then
  printf 'Usage: bash %s\n' "$0" >&2
  exit 2
fi

mkdir -p "$repository/data/records"
temporary_directory="$(mktemp -d "$repository/data/records/smoke.XXXXXX")"
server_pid=""

cleanup() {
  status=$?
  if [[ "$status" -ne 0 && -f "$temporary_directory/server.log" ]]; then
    printf 'check_server: server log follows\n' >&2
    cat "$temporary_directory/server.log" >&2
  fi
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$temporary_directory"
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

port="$(uv run --locked --no-sync --project "$repository" python -c '
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
')"
FACTORY_SIMULATOR_DATABASE_URL="duckdb:///$temporary_directory/runs.duckdb" \
  uv run --locked --no-sync --project "$repository" uvicorn \
  factory_simulator.api.main:app --host 127.0.0.1 --port "$port" \
  >"$temporary_directory/server.log" 2>&1 &
server_pid=$!

uv run --locked --no-sync --project "$repository" python - "$port" <<'PY'
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

address = f"http://127.0.0.1:{sys.argv[1]}/api/v1/manifests"
deadline = time.monotonic() + 20
while True:
    try:
        with urlopen(address, timeout=1) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"check_server: the request returned HTTP {response.status}"
                )
            manifests = json.load(response)["manifests"]
            if not manifests:
                raise RuntimeError(
                    "check_server: the server returned no example manifests"
                )
            break
    except HTTPError as error:
        raise RuntimeError(
            f"check_server: the request returned HTTP {error.code}"
        ) from None
    except (ConnectionError, TimeoutError, URLError):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "check_server: the server did not answer within 20 seconds"
            ) from None
        time.sleep(0.2)

print(
    "Smoke request passed: the temporary server returned example manifests."
)
PY
