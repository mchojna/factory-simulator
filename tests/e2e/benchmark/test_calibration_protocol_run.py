import tempfile
from dataclasses import replace
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import pytest
from factories import benchmark_client, plain_tiny_manifest, plain_tiny_scenario
from stress.playing import (
    PlayedRun,
    World,
    build_checks_digest,
    build_code_digest,
    build_solver_environment,
    play_world,
    settings_of,
)
from stress.protocol import (
    CalibrationProtocol,
    FrozenDefinitions,
    build_analysis_digest,
    build_protocol_line,
    check_evaluation,
)
from stress.report import Provenance, write_report

from factory_simulator.benchmark import client as benchmark

ROOT = Path(__file__).parents[3]


# An evaluation of the plain tiny factory on the evaluation seeds 1 and 2 of a protocol
# whose definitions are frozen from the identifiers the server gives, the code, checks
# and analysis of the repository and the settings of a time limit of 60 s. Its budget
# is 2 worlds: 2 seeds times 1 scenario.
@pytest.mark.slow
def test_an_evaluation_report_traces_its_frozen_definitions_and_its_seeds():
    manifest, scenario = plain_tiny_manifest(), plain_tiny_scenario()
    code = build_code_digest(ROOT / "src" / "factory_simulator")
    checks = build_checks_digest(ROOT / "tests")
    analysis = build_analysis_digest(ROOT / "tests")
    settings = settings_of(60.0)
    package_version = version("factory-simulator")
    runs: list[PlayedRun] = []
    violations: list[str] = []
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        frozen = FrozenDefinitions(
            version=package_version,
            code=code,
            solver_environment=build_solver_environment(),
            checks=checks,
            analysis=analysis,
            settings=settings,
            manifest_id=stored_manifest["id"],
            scenario_ids={scenario["name"]: scenario_id},
        )
        protocol = CalibrationProtocol(
            development_seeds=range(1),
            evaluation_seeds=range(1, 3),
            worlds=2,
            frozen=frozen,
        )
        check_evaluation(protocol, frozen, runs, [])
        for seed in protocol.evaluation_seeds:
            world = World(
                scenario=scenario["name"],
                scenario_id=scenario_id,
                manifest_id=stored_manifest["id"],
                scenario_content=scenario,
                seed=seed,
                replay=seed == protocol.evaluation_seeds[0],
            )
            played, failures = play_world(client, 60.0, code, checks, world)
            runs += played
            violations += failures
    check_evaluation(protocol, frozen, runs, [])
    provenance = Provenance(
        version=package_version,
        code=code,
        solver_environment=build_solver_environment(),
        checks=checks,
        analysis=analysis,
        time="2026-10-19T10:00:00",
        command="tests/stress -m stress --stress-evaluation",
        manifest_name=manifest["name"],
        manifest_id=stored_manifest["id"],
        seeds=protocol.evaluation_seeds,
        protocol=build_protocol_line(protocol, evaluation=True),
        settings=settings,
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = write_report(
            Path(directory), runs, violations, provenance, datetime(2026, 10, 19)
        )
        lines = (folder / "report.md").read_text().splitlines()

    assert violations == []
    assert lines[3:7] == [
        f"- Code: {code}",
        f"- Solver environment: {build_solver_environment()}",
        f"- Checks: {checks}",
        f"- Analysis: {analysis}",
    ]
    assert f"- Manifest: Plain tiny factory, {stored_manifest['id']}" in lines
    assert lines[10:12] == [
        "- Seeds: 1 to 2",
        "- Protocol: confirmatory evaluation of the frozen definitions; development "
        "seeds 0 to 0, evaluation seeds 1 to 2, a budget of 2 worlds",
    ]
    assert f"| Plain tiny scenario | {scenario_id} |" in lines
    assert lines[13].startswith("- Worlds: 2 played, ")
    assert {(run.seed, run.play) for run in runs} == {(1, 1), (1, 2), (2, 1)}
    assert {
        (run.version, run.code, run.solver_environment, run.settings) for run in runs
    } == {(package_version, code, build_solver_environment(), settings)}
    # A protocol frozen under another version, code, solver environment, settings or
    # scenario identifier refuses every run played under these definitions.
    for changes in (
        {"version": "0.0.0"},
        {"code": "0ld"},
        {"solver_environment": "scipy=0.0.0"},
        {"settings": settings_of(30.0)},
        {"scenario_ids": {scenario["name"]: "another-scenario"}},
    ):
        other = replace(frozen, **changes)
        with pytest.raises(ValueError) as refused:
            check_evaluation(replace(protocol, frozen=other), other, runs, [])
        assert str(refused.value) == (
            "runs of the evaluation seeds under other definitions in the index: "
            f"{len(runs)}; a new evaluation takes seeds no run has read"
        )
