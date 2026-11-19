import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from factories import benchmark_client, hidden_yield_bodies
from stress.controls import build_controls
from stress.playing import (
    PlayedRun,
    World,
    agents_of,
    build_solver_environment,
    play_world,
)
from stress.report import INFORMATION_RULE, Provenance, write_report

from factory_simulator.benchmark import client as benchmark


# The plain tiny factory with a hidden board yield, named as the scenario of the
# library that hides groups, and its visible twin, played by the agents of the stress
# test on seed 0. The two worlds hold the same draws, so no decisions and the reference
# make the same profit in both, and the report pairs them under the treatment `hidden`.
@pytest.mark.slow
def test_the_report_pairs_a_hidden_yield_with_its_visible_twin():
    manifest, scenario = hidden_yield_bodies()
    scenario["name"] = "hidden-groups"
    [(_, twin)] = build_controls({"hidden-groups": scenario}, ["hidden-groups"])
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        runs: list[PlayedRun] = []
        violations: list[str] = []
        identifiers: list[str] = []
        for content in (scenario, twin):
            scenario_id = benchmark.send(client, "POST", path, content)["id"]
            identifiers.append(scenario_id)
            world = World(
                scenario=content["name"],
                scenario_id=scenario_id,
                manifest_id=stored_manifest["id"],
                scenario_content=content,
                seed=0,
                replay=False,
                agents=agents_of(content["hidden"]),
            )
            played, failures = play_world(client, 60.0, "c0de", "c4ec5", world)
            runs += played
            violations += failures
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-19T10:00:00",
        command="tests/e2e",
        manifest_name=manifest["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = write_report(
            Path(directory), runs, violations, provenance, datetime(2026, 10, 19)
        )
        report = (folder / "report.md").read_text()

    assert violations == []
    assert [message for run in runs for message in run.violations] == []
    profits = {(run.scenario, run.agent): run.profit for run in runs}
    for agent in ("no_decisions", "reference"):
        assert profits["hidden-groups", agent] == profits["hidden-groups-shown", agent]
    assert ("hidden-groups-shown", "informed_optimizer") not in profits
    section = report.split("## Information controls\n\n")[1].split("\n\n## ")[0]
    lines = section.splitlines()
    assert lines[0] == INFORMATION_RULE
    assert len(lines) == 5
    prefix = (
        f"| hidden-groups | hidden | hidden-groups-shown | {identifiers[1]} "
        "| manifest, seeds, horizon, start, demand shapes, disruptions, forecasts "
        "| 1 | "
    )
    # In the plain tiny factory the buffered rolling optimizer earns what the reference
    # earns in the scenario and in its twin: it scores 1 in both and the effect is 0.
    scores = report.split("## Scores\n\n")[1].split("\n\n## ")[0].splitlines()
    for name, agent in (
        ("hidden-groups", "buffered_rolling_optimizer"),
        ("hidden-groups-shown", "buffered_rolling_optimizer"),
    ):
        row = next(line for line in scores if line.startswith(f"| {name} | {agent} |"))
        assert row.split(" | ")[3:8] == ["1", "1.000", "1.000", "1.000", "1.000"]
    assert lines[4] == f"{prefix}0.000 | - | - | - |"
