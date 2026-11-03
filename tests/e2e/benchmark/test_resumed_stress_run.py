from dataclasses import replace
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import httpx2 as httpx
import pytest
from factories import plain_tiny_manifest, plain_tiny_scenario
from stress.playing import (
    AGENTS,
    PlayedRun,
    RunIdentity,
    World,
    append_to_index,
    build_solver_environment,
    current_runs,
    missing_run_violations,
    play_worlds,
    read_index,
    settings_of,
    started_server,
    unique_runs,
    worlds_left,
)
from stress.report import Provenance, write_report
from stress.test_playing import HAND_WORLDS, SOLVER_ENVIRONMENT, hand_world_rows

from factory_simulator.benchmark import client as benchmark


# The report of the runs of an index and the violations, by its sections.
def report_sections(
    folder: Path, runs: list[PlayedRun], violations: list[str], manifest_id: str
) -> dict[str, str]:
    provenance = Provenance(
        version=version("factory-simulator"),
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=manifest_id,
        seeds=range(2),
        protocol="development",
        settings=settings_of(60.0),
    )
    report = write_report(folder, runs, violations, provenance, datetime(2026, 10, 20))
    sections = (report / "report.md").read_text().split("\n## ")
    return {section.split("\n")[0]: section for section in sections[1:]}


# A campaign of the plain tiny factory on seeds 0 and 1, seed 0 played twice, played
# whole into one index and, into another, stopped after play 1 of seed 0 and resumed.
@pytest.mark.slow
def test_a_resumed_campaign_plays_every_repeat_and_scores_as_an_uninterrupted_one(
    tmp_path: Path,
):
    whole_index = tmp_path / "whole" / "stress-runs.csv"
    resumed_index = tmp_path / "resumed" / "stress-runs.csv"
    settings = settings_of(60.0)
    package_version = version("factory-simulator")
    solver_environment = build_solver_environment()
    with (
        started_server(tmp_path / "stress.duckdb") as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        worlds = [
            World(
                scenario=plain_tiny_scenario()["name"],
                scenario_id=scenario["id"],
                manifest_id=stored_manifest["id"],
                scenario_content=plain_tiny_scenario(),
                seed=seed,
                replay=seed == 0,
            )
            for seed in (0, 1)
        ]
        whole_index.parent.mkdir()
        resumed_index.parent.mkdir()
        play_worlds(url, worlds, 2, 60.0, "c0de", "c4ec5", whole_index)
        stopped = [replace(worlds[0], replay=False), worlds[1]]
        play_worlds(url, stopped, 2, 60.0, "c0de", "c4ec5", resumed_index)
        stopped_runs = read_index(resumed_index)
        identity = RunIdentity(
            settings=settings,
            version=package_version,
            code="c0de",
            solver_environment=solver_environment,
        )
        before = missing_run_violations(identity, stopped_runs, worlds)
        left = worlds_left(identity, stopped_runs, worlds)
        violations = play_worlds(url, left, 2, 60.0, "c0de", "c4ec5", resumed_index)
    whole, whole_differing = unique_runs(read_index(whole_index))
    resumed, resumed_differing = unique_runs(read_index(resumed_index))
    after = missing_run_violations(identity, resumed, worlds)
    stopped_report = report_sections(
        tmp_path / "stopped-report", stopped_runs, before, stored_manifest["id"]
    )
    whole_report = report_sections(
        tmp_path / "whole-report", whole, whole_differing, stored_manifest["id"]
    )
    resumed_report = report_sections(
        tmp_path / "resumed-report",
        resumed,
        resumed_differing + after,
        stored_manifest["id"],
    )
    repeats = {(run.agent, run.violations) for run in resumed if run.play == 2}

    assert [world.seed for world in left] == [0]
    assert violations == []
    assert len(before) == 1
    assert before[0].startswith("Plain tiny scenario seed 0: the index holds no run")
    assert after == []
    assert repeats == {(agent, ()) for agent in AGENTS}
    assert resumed_report["Scores"] == whole_report["Scores"]
    assert resumed_report["Violations"].startswith("Violations\n\nNone.")
    assert stopped_report["Violations"].startswith(f"Violations\n\n- {before[0]}\n")


# The rolling optimizer of a hand campaign on seeds 0 to 2 of steady market, seed 0
# played twice: no decisions at -100 and the reference at 900 in every world, so a
# score is (profit + 100) / 1000. Under the earlier solver environment it makes 400,
# 0.5, in every seed; under the current one 600, 700 and 800, 0.7, 0.8 and 0.9.
def hand_profits(rolling: tuple[int, int, int]) -> dict[tuple[int, str], int]:
    profits = {(seed, agent): 0 for seed in range(3) for agent in AGENTS}
    for seed in range(3):
        profits[seed, "no_decisions"] = -100
        profits[seed, "reference"] = 900
        profits[seed, "rolling_optimizer"] = rolling[seed]
    return profits


# A campaign whose index holds every world under an earlier solver environment, resumed
# under the current one, stopped after seeds 0 and 1 and resumed again.
def test_a_campaign_resumed_under_another_solver_environment_reads_its_own_runs_only(
    tmp_path: Path,
):
    index = tmp_path / "stress-runs.csv"
    settings, package_version = "time_limit=60.0", "0.4.0"
    earlier = "scipy=1.17.0, highs=1.11.0"
    for world in HAND_WORLDS:
        rows = hand_world_rows(world, hand_profits((400, 400, 400)), "earlier")
        append_to_index(
            index, [replace(run, solver_environment=earlier) for run in rows]
        )
    current = hand_profits((600, 700, 800))
    identity = RunIdentity(
        settings=settings,
        version=package_version,
        code="c0de",
        solver_environment=SOLVER_ENVIRONMENT,
    )
    left = worlds_left(identity, read_index(index), HAND_WORLDS)
    for world in left[:2]:
        append_to_index(index, hand_world_rows(world, current, "current"))
    stopped = read_index(index)
    stopped_runs, _ = unique_runs(current_runs(identity, stopped, HAND_WORLDS))
    missing = missing_run_violations(identity, stopped, HAND_WORLDS)
    resumed_left = worlds_left(identity, stopped, HAND_WORLDS)
    for world in resumed_left:
        append_to_index(index, hand_world_rows(world, current, "current"))
    resumed = read_index(index)
    resumed_runs, differing = unique_runs(current_runs(identity, resumed, HAND_WORLDS))
    provenance = Provenance(
        version=package_version,
        code="c0de",
        solver_environment=SOLVER_ENVIRONMENT,
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name="Plain tiny factory",
        manifest_id="m1",
        seeds=range(3),
        protocol="development",
        settings=settings,
    )
    stopped_report = write_report(
        tmp_path, stopped_runs, missing, provenance, datetime(2026, 10, 20, 10)
    )
    resumed_report = write_report(
        tmp_path, resumed_runs, differing, provenance, datetime(2026, 10, 20, 11)
    )
    stopped_lines = (stopped_report / "report.md").read_text().splitlines()
    resumed_lines = (resumed_report / "report.md").read_text().splitlines()

    assert left == HAND_WORLDS
    assert missing == [
        "steady-market seed 2: the index holds no run of "
        + ", ".join(f"{agent} play 1" for agent in AGENTS)
    ]
    assert [world.seed for world in resumed_left] == [2]
    assert differing == []
    assert {run.solver_environment for run in resumed_runs} == {SOLVER_ENVIRONMENT}
    assert len(resumed) == 2 * 3 * len(AGENTS) + 2 * len(AGENTS)
    assert f"- Solver environment: {SOLVER_ENVIRONMENT}" in resumed_lines
    # Seeds 0 and 1 score 0.7 and 0.8. Seed 2 under the earlier environment, 0.5, is
    # left out; with it the row would read 3 worlds and a mean of 0.667.
    assert (
        "| steady-market | rolling_optimizer | integer | 2 | 0.750 | 0.725 | 0.750 "
        "| 0.775 | - |"
    ) in stopped_lines
    assert (
        "| steady-market | rolling_optimizer | integer | 3 | 0.800 | 0.750 | 0.800 "
        "| 0.850 | - |"
    ) in resumed_lines
