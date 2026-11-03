import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2 as httpx

import factory_simulator


# A free local port for a server started by a test.
def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# Read the answer of a served route with exact numbers.
def read_answer(response: httpx.Response) -> dict[str, Any]:
    return json.loads(response.text, parse_float=Decimal)


# Wait until a started server answers, for 30 seconds at most.
def wait_until_ready(client: httpx.Client) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            client.get("/api/v1/manifests")
            return
        except httpx.TransportError:
            time.sleep(0.1)
    raise TimeoutError("the server did not answer within 30 seconds")


# An application served by uvicorn in a process of its own, on a database URL, and a
# client of it. With no Python interpreter given it serves the package of `src/`;
# with one it serves the package installed for it. Leaving the block kills the process.
@contextmanager
def served_app(
    database_url: str, python: Path | None = None, load_examples: bool = False
) -> Generator[httpx.Client]:
    port = free_port()
    command = [str(python or sys.executable), "-m", "uvicorn"]
    command.append("factory_simulator.api.main:app")
    if python is None:
        source = Path(factory_simulator.__file__).parents[1]
        command += ["--app-dir", str(source)]
    command += ["--port", str(port)]
    settings = {
        "FACTORY_SIMULATOR_DATABASE_URL": database_url,
        "FACTORY_SIMULATOR_LOAD_EXAMPLES": "true" if load_examples else "false",
    }
    server = subprocess.Popen(
        command,
        env=os.environ | settings,
        cwd=Path(database_url.removeprefix("duckdb:///")).parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=None) as client:
            wait_until_ready(client)
            yield client
    finally:
        server.kill()
        server.wait()
