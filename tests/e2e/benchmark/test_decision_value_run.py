import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from factories import benchmark_client, plain_tiny_manifest, plain_tiny_scenario
from stress.playing import PlayedRun, World, build_solver_environment, play_world
from stress.report import DECISION_VALUE_RULE, DECISION_VALUES, Provenance, write_report

from factory_simulator.benchmark import client as benchmark


# The plain tiny factory, played by the agents of the stress test on seed 0 in two
# worlds named as scenarios of the library: steady market from cash 1000, 16 chips and
# 8 boards, and the cash squeeze from cash -1000 and 8 monitors, where no buy can ever
# pass. In the squeeze no decisions loses the 12 monitors ordered for 120 and keeps 8
# at 2, -104; the reference ships the 8 for 8 * 49 = 392 and loses 4 for 40, 352, and
# buys nothing. In steady market no decisions makes -114.4; the reference makes 4
# monitors from the 8 boards and 4 from the 16 chips, ships them in periods 2 and 3 and
# loses the 4 of period 1, 392 - 40 - 24 = 328, and no chip it buys is sold in time.
# Both scores are 1, while the squeeze closes all 3 periods below the credit limit.
@pytest.mark.slow
def test_a_report_pairs_the_score_of_a_liquidation_with_its_outcomes_and_reading():
    squeeze: dict[str, Any] = plain_tiny_scenario() | {
        "name": "cash-squeeze",
        "start": {"cash": "-1000", "stock": {"main": {"monitor": "8"}}},
    }
    steady: dict[str, Any] = plain_tiny_scenario() | {"name": "steady-market"}
    runs: list[PlayedRun] = []
    violations: list[str] = []
    with benchmark_client() as client:
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        for scenario in (steady, squeeze):
            scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
            world = World(
                scenario=scenario["name"],
                scenario_id=scenario_id,
                manifest_id=stored_manifest["id"],
                scenario_content=scenario,
                seed=0,
                replay=False,
            )
            world_runs, world_violations = play_world(
                client, 60.0, "c0de", "c4ec5", world
            )
            runs += world_runs
            violations += world_violations
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/e2e",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = write_report(
            Path(directory), runs, violations, provenance, datetime(2026, 10, 20)
        )
        report = (folder / "report.md").read_text()

    assert violations == []
    section = report.split("## Decision value\n\n")[1].split("\n\n## ")[0]
    rule, absolute, against = section.split("\n\n")
    assert rule == DECISION_VALUE_RULE
    assert absolute.splitlines()[2:] == [
        "| cash-squeeze | 1 | -104.000 | 352.000 | 456.000 | 352.000 | 0.000 | 0.667 "
        "| 0.667 | 4.000 | 0.000 | 3.000 |",
        "| steady-market | 1 | -114.400 | 328.000 | 442.400 | 328.000 | 0.000 | 0.667 "
        "| 0.667 | 4.000 | 0.000 | 0.000 |",
    ]
    reading, evidence = DECISION_VALUES["cash-squeeze"]
    assert against.splitlines()[2:] == [
        f"| cash-squeeze | 1 | 0.000 | 24.000 | 0.000 | 13.600 | {reading} "
        f"| {evidence} |"
    ]
