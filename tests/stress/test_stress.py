import json
import sys
from datetime import datetime
from importlib.metadata import version
from typing import cast

import httpx2 as httpx
import pytest

from factory_simulator.api.services.examples import EXAMPLES, MANIFEST_FILE
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.program.solve import GAP_LIMIT, NODE_LIMIT
from stress.checks import violations_of_play
from stress.controls import build_controls
from stress.playing import (
    RunIdentity,
    World,
    agents_of,
    build_checks_digest,
    build_code_digest,
    build_solver_environment,
    current_runs,
    missing_run_violations,
    play_worlds,
    read_index,
    recheck_index,
    set_aside_cut_row,
    settings_of,
    started_server,
    unique_runs,
    worlds_left,
)
from stress.protocol import (
    PROTOCOL,
    FrozenDefinitions,
    build_analysis_digest,
    build_protocol_line,
    check_development_seeds,
    check_protocol,
    record_evaluation_start,
)
from stress.report import Provenance, write_report


@pytest.mark.stress
def test_every_world_of_the_library_plays_without_a_violation(
    pytestconfig: pytest.Config, capsys: pytest.CaptureFixture[str]
):
    seeds = range(cast(int, pytestconfig.getoption("--stress-seeds")))
    names = cast(str, pytestconfig.getoption("--stress-scenarios"))
    workers = cast(int, pytestconfig.getoption("--stress-workers"))
    time_limit = cast(float, pytestconfig.getoption("--stress-time-limit"))
    evaluation = cast(bool, pytestconfig.getoption("--stress-evaluation"))
    if evaluation:
        check_protocol(PROTOCOL)
        assert names == "all" and len(seeds) == len(PROTOCOL.evaluation_seeds), (
            "an evaluation plays every scenario on the evaluation seeds of the protocol"
        )
        seeds = PROTOCOL.evaluation_seeds
    else:
        check_development_seeds(PROTOCOL, seeds)
    records = pytestconfig.rootpath / "data" / "records"
    index = records / "stress-runs.csv"
    settings = settings_of(time_limit)
    package_version = version("factory-simulator")
    code = build_code_digest(pytestconfig.rootpath / "src" / "factory_simulator")
    solver_environment = build_solver_environment()
    checks = build_checks_digest(pytestconfig.rootpath / "tests")
    analysis = build_analysis_digest(pytestconfig.rootpath / "tests")
    identity = RunIdentity(
        settings=settings,
        version=package_version,
        code=code,
        solver_environment=solver_environment,
    )
    with capsys.disabled():
        set_aside_cut_row(index)
    with (
        started_server(records / "stress.duckdb") as url,
        httpx.Client(base_url=url, timeout=None) as client,
    ):
        manifest = json.loads((EXAMPLES / MANIFEST_FILE).read_bytes())
        manifest_id = benchmark.send(client, "POST", "/manifests", manifest)["id"]
        path = f"/manifests/{manifest_id}/scenarios"
        library = [
            json.loads(file.read_bytes())
            for file in sorted((EXAMPLES / "scenarios").glob("*.json"))
        ]
        scenarios = list(library)
        if names != "all":
            chosen = names.split(",")
            scenarios = [
                scenario for scenario in scenarios if scenario["name"] in chosen
            ]
            assert len(scenarios) == len(chosen), f"unknown scenarios in {names}"
        # The information controls of the chosen scenarios play beside them.
        chosen_names = [scenario["name"] for scenario in scenarios]
        controls = build_controls(
            {scenario["name"]: scenario for scenario in library}, chosen_names
        )
        for _, content in controls:
            if content["name"] not in chosen_names:
                chosen_names.append(content["name"])
                scenarios.append(content)
        scenario_ids = [
            benchmark.send(client, "POST", path, scenario)["id"]
            for scenario in scenarios
        ]
        if evaluation:
            current = FrozenDefinitions(
                version=package_version,
                code=code,
                solver_environment=solver_environment,
                checks=checks,
                analysis=analysis,
                settings=settings,
                manifest_id=manifest_id,
                scenario_ids=dict(zip(chosen_names, scenario_ids, strict=True)),
            )
            record_evaluation_start(
                index, PROTOCOL, current, datetime.now().isoformat(timespec="seconds")
            )
        worlds = [
            World(
                scenario=scenario["name"],
                scenario_id=scenario_id,
                manifest_id=manifest_id,
                scenario_content=scenario,
                seed=seed,
                replay=seed == seeds[0],
                agents=agents_of(scenario.get("hidden") or []),
            )
            for scenario, scenario_id in zip(scenarios, scenario_ids, strict=True)
            for seed in seeds
        ]
        with capsys.disabled():
            print(flush=True)
            violations = recheck_index(
                client, index, identity, checks, violations_of_play
            )
            left = worlds_left(identity, read_index(index), worlds)
            print(f"worlds to play: {len(left)} of {len(worlds)}", flush=True)
            violations += play_worlds(
                url, left, workers, time_limit, code, checks, index
            )
    held = read_index(index)
    violations += missing_run_violations(identity, held, worlds)
    runs, differing = unique_runs(current_runs(identity, held, worlds))
    violations += differing
    now = datetime.now()
    provenance = Provenance(
        version=package_version,
        code=code,
        solver_environment=solver_environment,
        checks=checks,
        analysis=analysis,
        time=now.isoformat(timespec="seconds"),
        command=" ".join(sys.argv[1:]),
        manifest_name=manifest["name"],
        manifest_id=manifest_id,
        seeds=seeds,
        protocol=build_protocol_line(PROTOCOL, evaluation=evaluation),
        settings=f"{settings}, node_limit={NODE_LIMIT}, gap_limit={GAP_LIMIT}",
    )
    folder = write_report(
        pytestconfig.rootpath / "data" / "reports", runs, violations, provenance, now
    )
    with capsys.disabled():
        print(f"report: {folder}", flush=True)
    lines = [
        f"{run.scenario} seed {run.seed} {run.agent} {run.run_id}: {message}"
        for run in runs
        if run.checks == checks
        for message in run.violations
    ]
    lines += violations
    assert lines == [], "\n".join(lines)
