import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def demo_server(tmp_path: Path) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    database = tmp_path / "demo server.duckdb"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        }
    } | {
        "FACTORY_SIMULATOR_DATABASE_URL": f"duckdb:///{database}",
        "FACTORY_SIMULATOR_LOAD_EXAMPLES": "false",
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "factory_simulator.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPOSITORY,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    address = f"http://127.0.0.1:{port}/api/v1"
    deadline = time.monotonic() + 15
    while True:
        if server.poll() is not None:
            pytest.fail("demo server stopped before it accepted requests")
        try:
            with urlopen(f"{address}/manifests", timeout=1):
                break
        except ConnectionError, TimeoutError, URLError:
            if time.monotonic() >= deadline:
                server.terminate()
                server.wait(timeout=10)
                pytest.fail("demo server did not start within 15 seconds")
            time.sleep(0.1)
    try:
        yield address
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


@pytest.mark.slow
def test_no_decisions_demo_runs_a_bounded_scenario_and_writes_its_archive(
    demo_server: str, tmp_path: Path
):
    output = tmp_path / "demo output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.run_without_decisions.run",
            "--server",
            demo_server,
            "--seed",
            "33",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary_path = Path(result.stdout.strip())
    summary = json.loads(summary_path.read_text())
    assert summary["seed"] == 33
    assert summary["periods"] == 3
    assert (summary_path.parent / f"{summary['run_id']}.zip").is_file()


@pytest.mark.slow
def test_plan_production_uses_a_mathematical_optimizer_and_saves_its_trace(
    demo_server: str, tmp_path: Path
):
    output = tmp_path / "optimizer output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.plan_production.run",
            "--server",
            demo_server,
            "--seed",
            "34",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(Path(result.stdout.strip()).read_text())
    assert summary["details"]["optimizer"] == "myopic"
    assert len(summary["details"]["periods"]) == 3
    assert any(period["solves"] for period in summary["details"]["periods"])


@pytest.mark.slow
def test_check_decisions_checks_and_submits_a_shipment_through_http(
    demo_server: str, tmp_path: Path
):
    output = tmp_path / "checked output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.check_decisions.run",
            "--server",
            demo_server,
            "--seed",
            "35",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(Path(result.stdout.strip()).read_text())
    assert summary["details"]["check_outcomes"]
    assert all(outcome["accepted"] for outcome in summary["details"]["check_outcomes"])
    assert summary["periods"] == 3


@pytest.mark.slow
def test_resume_demo_continues_the_same_stored_run(demo_server: str, tmp_path: Path):
    output = tmp_path / "resume output"
    first = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.resume_a_run.run",
            "--server",
            demo_server,
            "--seed",
            "36",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    checkpoint_path = Path(first.stdout.strip())
    checkpoint = json.loads(checkpoint_path.read_text())

    resumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.resume_a_run.run",
            "--server",
            demo_server,
            "--run-id",
            checkpoint["run_id"],
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert resumed.returncode == 0, resumed.stderr
    summary = json.loads(Path(resumed.stdout.strip()).read_text())
    assert summary["run_id"] == checkpoint["run_id"]
    assert summary["periods"] == 3
    assert checkpoint["next_period"] == 2


@pytest.mark.slow
def test_fork_demo_records_parent_and_fork_from_the_selected_period(
    demo_server: str, tmp_path: Path
):
    output = tmp_path / "fork output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.fork_a_run.run",
            "--server",
            demo_server,
            "--seed",
            "37",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary_path = Path(result.stdout.strip())
    summary = json.loads(summary_path.read_text())
    details = summary["details"]
    assert details["forked_from_period"] == 2
    assert details["forked_from"] != summary["run_id"]
    assert (output / details["forked_from"] / "summary.json").is_file()
    assert summary["periods"] == 3


@pytest.mark.slow
def test_inspect_record_reads_a_finished_run_archive_without_a_server_argument(
    demo_server: str, tmp_path: Path
):
    run_output = tmp_path / "run output"
    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.run_without_decisions.run",
            "--server",
            demo_server,
            "--seed",
            "38",
            "--output",
            str(run_output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run_result.returncode == 0, run_result.stderr
    summary_path = Path(run_result.stdout.strip())
    summary = json.loads(summary_path.read_text())
    archive = summary_path.parent / f"{summary['run_id']}.zip"

    output = tmp_path / "inspection output"
    inspected = subprocess.run(
        [
            sys.executable,
            "-m",
            "demos.inspect_a_record.run",
            "--archive",
            str(archive),
            "--output",
            str(output),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert inspected.returncode == 0, inspected.stderr
    inspection_path = Path(inspected.stdout.strip())
    inspection = json.loads(inspection_path.read_text())
    assert inspection["run_id"] == summary["run_id"]
    assert "results.parquet" in inspection["files"]
    assert "manifest.json" in inspection["files"]


@pytest.mark.parametrize(
    "module",
    [
        "demos.single_prompt_planning.run",
        "demos.tool_guided_planning.run",
        "demos.coordinated_planning.run",
    ],
)
def test_model_commands_require_credentials_instead_of_returning_canned_answers(
    module: str, tmp_path: Path
):
    environment = {
        key: value for key, value in os.environ.items() if key != "ANTHROPIC_API_KEY"
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            "--provider",
            "anthropic",
            "--model",
            "chosen-model",
            "--output",
            str(tmp_path / "output"),
        ],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "ANTHROPIC_API_KEY" in result.stderr
    assert not (tmp_path / "output").exists()
