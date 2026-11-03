import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from factories import benchmark_client, hidden_yield_bodies
from stress.playing import World, agents_of, build_solver_environment, play_world
from stress.report import DISCLOSURE_RULE, Provenance, write_report

from factory_simulator.benchmark import client as benchmark


# The plain tiny factory with a hidden board yield, named as the scenario of the
# library that hides groups, played by the agents of the stress test on seed 0 alone.
# The report pairs the informed and rolling runs at the factor 1.2 in one world.
@pytest.mark.slow
def test_a_report_of_one_seed_pairs_the_informed_and_rolling_runs_as_a_diagnostic():
    manifest, scenario = hidden_yield_bodies()
    scenario["name"] = "hidden-groups"
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario="hidden-groups",
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
            agents=agents_of(scenario["hidden"]),
        )
        runs, violations = play_world(client, 60.0, "c0de", "c4ec5", world)
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
    assert {run.agent for run in runs} >= {
        "rolling_optimizer",
        "buffered_rolling_optimizer",
        "informed_optimizer",
        "buffered_informed_optimizer",
    }
    section = report.split("## Disclosure effect\n\n")[1].split("\n\n## ")[0]
    lines = section.splitlines()
    assert lines[0] == DISCLOSURE_RULE
    assert lines[0].endswith(
        "Every disclosure effect is a diagnostic; one of a single seed has no "
        "standard error and no bounds."
    )
    assert len(lines) == 5
    prefix = (
        "| hidden-groups | ranges of hidden groups disclosed "
        "| buffered_informed_optimizer | buffered_rolling_optimizer | 1 | "
    )
    # In the plain tiny factory the informed and the rolling optimizer at the factor
    # 1.2 earn what the reference earns: each scores 1 and the effect is 0.
    scores = report.split("## Scores\n\n")[1].split("\n\n## ")[0].splitlines()
    for name, agent in (
        ("hidden-groups", "buffered_informed_optimizer"),
        ("hidden-groups", "buffered_rolling_optimizer"),
    ):
        row = next(line for line in scores if line.startswith(f"| {name} | {agent} |"))
        assert row.split(" | ")[3:8] == ["1", "1.000", "1.000", "1.000", "1.000"]
    assert lines[4] == f"{prefix}0.000 | - | - | - |"
