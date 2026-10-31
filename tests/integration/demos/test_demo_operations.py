import zipfile
from pathlib import Path
from typing import cast

import httpx2 as httpx
import pytest
from factories.client import app_of
from fastapi.testclient import TestClient

from demos.fork_a_run.run import FORK_PERIOD
from demos.utils.cli import save_finished_run
from demos.utils.client import scenario_with_product_stock, start_demo_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


@pytest.mark.slow
def test_demo_http_operations_survive_restart_and_export_a_fork(
    tmp_path: Path,
):
    database = tmp_path / "demo operations.duckdb"
    database_url = f"duckdb:///{database}"
    output = tmp_path / "demo outputs"
    with TestClient(
        app_of(database_url, load_examples=False),
        base_url="http://testserver/api/v1",
    ) as test_client:
        client = cast(httpx.Client, test_client)
        run = start_demo_run(client, 39, scenario_with_product_stock("4.000"))
        run_id = str(run["id"])
        observation = benchmark.read(client, f"/runs/{run_id}/observation")
        decisions: list[JsonObject] = [
            {
                "kind": "ship",
                "order": order["id"],
                "quantity": order["quantity"],
            }
            for order in observation["customer_orders"]
        ]
        outcomes = benchmark.create_check(
            client, run_id, int(observation["period"]), decisions
        )
        assert outcomes and all(outcome["accepted"] for outcome in outcomes)
        benchmark.send(
            client,
            "POST",
            f"/runs/{run_id}/decisions",
            {"period": observation["period"], "decisions": decisions},
        )

    with TestClient(
        app_of(database_url, load_examples=False),
        base_url="http://testserver/api/v1",
    ) as test_client:
        client = cast(httpx.Client, test_client)
        run = benchmark.read(client, f"/runs/{run_id}")
        parent_result = benchmark.play_run(client, run, no_decisions)
        parent_summary = save_finished_run(
            client, "integration-demo", run, parent_result, output, {"role": "parent"}
        )
        fork = benchmark.send(
            client,
            "POST",
            f"/runs/{run_id}/forks",
            {"period": FORK_PERIOD},
        )
        fork_result = benchmark.play_run(client, fork, no_decisions)
        fork_summary = save_finished_run(
            client,
            "integration-demo",
            fork,
            fork_result,
            output,
            {"forked_from": run_id, "forked_from_period": FORK_PERIOD},
        )

    assert parent_summary.is_file()
    assert fork_summary.is_file()
    for summary_path in (parent_summary, fork_summary):
        with zipfile.ZipFile(
            summary_path.with_name(f"{summary_path.parent.name}.zip")
        ) as archive:
            assert archive.testzip() is None
            assert "results.parquet" in archive.namelist()
