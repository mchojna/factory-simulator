import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from factories import api_client, database_file, run_to_the_end, start_run


@pytest.mark.slow
def test_the_transport_command_reads_a_stopped_record_and_keeps_existing_artifacts(
    tmp_path: Path,
):
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            run_to_the_end(client, run)
            assert client.get(f"/api/v1/runs/{run['id']}/export").status_code == 200
        destination = tmp_path / "transport.zip"
        command = [
            sys.executable,
            "-m",
            "factory_simulator.api.record.transport",
            url.removeprefix("duckdb:///"),
            str(destination),
        ]
        environment = os.environ | {
            "PYTHONPATH": str(Path(__file__).parents[3] / "src")
        }
        first = subprocess.run(
            command, env=environment, capture_output=True, text=True, check=False
        )
        assert first.returncode == 0, first.stderr
        original = destination.read_bytes()
        second = subprocess.run(
            command, env=environment, capture_output=True, text=True, check=False
        )
        assert second.returncode == 1
        assert destination.read_bytes() == original
    with zipfile.ZipFile(destination) as archive:
        description = json.loads(archive.read("operations.json"))
    assert description["kind"] == "transport"
    assert description["checked_body_chunks"] > 0
