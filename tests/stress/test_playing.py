import csv
import hashlib
import http.client
import os
import platform
import re
import tempfile
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import httpx2 as httpx
import pytest
from factories import (
    benchmark_client,
    example_count,
    hidden_yield_bodies,
    plain_tiny_manifest,
    plain_tiny_scenario,
    play_no_decisions,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.benchmark import client as benchmark
from stress.checks import JsonObject, Play, violations_of_play
from stress.playing import (
    AGENTS,
    COLUMNS,
    MEASURE_PATHS,
    OUTCOME_PATHS,
    AgentPlay,
    PlayedRun,
    RunIdentity,
    World,
    agents_of,
    append_to_index,
    build_checks_digest,
    build_code_digest,
    build_solver_environment,
    current_runs,
    indexed_run,
    measure_value,
    missing_run_violations,
    play_worlds,
    play_worlds_in_pool,
    read_index,
    recheck_index,
    rechecked_runs,
    row_key_of,
    set_aside_cut_row,
    settings_of,
    started_server,
    unique_runs,
    worlds_left,
)
from stress.report import Provenance, scores_of, write_report

# The solver environment of the rows of hand runs.
SOLVER_ENVIRONMENT = "scipy=1.18.1, highs=1.12.0"
# The identity of the rows of `hand_run`.
HAND_IDENTITY = RunIdentity(
    settings="time_limit=60.0",
    version="0.4.0",
    code="c0de",
    solver_environment=SOLVER_ENVIRONMENT,
)


def hand_run(agent: str, seed: int = 0, **changes: object) -> PlayedRun:
    run = PlayedRun(
        scenario="steady-market",
        scenario_id="s1",
        seed=seed,
        agent=agent,
        play=1,
        run_id=f"{agent}-{seed}",
        profit=Decimal(0),
        seconds=1.5,
        solves=0,
        solves_at_time_limit=0,
        solves_without_solution=0,
        dropped=None,
        fitted=None,
        relaxed_program_value=None,
        linear=None,
        largest_gap=None,
        violations=(),
        settings="time_limit=60.0",
        version="0.4.0",
        code="c0de",
        solver_environment=SOLVER_ENVIRONMENT,
        checks="c4ec5",
        time="2026-10-12T10:00:00",
        measures=dict.fromkeys(MEASURE_PATHS, Decimal(0)),
    )
    return replace(run, **changes)


# Checker B: the checks of a stored play, and one more violation in every run of the
# rolling optimizer.
def checker_b(
    agent: str, description: JsonObject, play: Play, first: Play | None
) -> list[str]:
    violations = violations_of_play(agent, description, play, first)
    if agent == "rolling_optimizer":
        violations.append("checker B finds a violation")
    return violations


# The rows of a complete world of the plain tiny factory in seed 0 checked by the checks
# `c4ec5`, each with the identifier of its own run of no decisions stored over HTTP.
def stored_world(client: httpx.Client) -> list[PlayedRun]:
    stored_manifest = benchmark.send(
        client, "POST", "/manifests", plain_tiny_manifest()
    )
    path = f"/manifests/{stored_manifest['id']}/scenarios"
    scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
    runs: list[PlayedRun] = []
    for agent in AGENTS:
        run, _ = play_no_decisions(client, scenario["id"], 0)
        runs.append(hand_run(agent, run_id=run["id"], profit=Decimal("-114.4")))
    return runs


# The worlds of seeds 0 to 2 of steady market, seed 0 played twice.
HAND_WORLDS = [
    World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=seed,
        replay=seed == 0,
    )
    for seed in range(3)
]


# The rows of a world of hand profits, by seed and agent, in the order of a play: the
# agents of the world in play 1, then in play 2 when it is played twice; `attempt`
# names the runs.
def hand_world_rows(
    world: World, profits: dict[tuple[int, str], int], attempt: str
) -> list[PlayedRun]:
    numbers = (1, 2) if world.replay else (1,)
    return [
        hand_run(
            agent,
            world.seed,
            play=number,
            run_id=f"{agent}-{world.seed}-{number}-{attempt}",
            profit=Decimal(profits[world.seed, agent]),
        )
        for number in numbers
        for agent in world.agents
    ]


# The rows of both plays of a world of seed 0, played twice.
def both_plays(agents: tuple[str, ...]) -> list[PlayedRun]:
    return [
        hand_run(agent, play=play, run_id=f"{agent}-0-{play}")
        for play in (1, 2)
        for agent in agents
    ]


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# A client whose every answer is 500: a check that reads a stored play through it
# raises.
def refusing_client() -> httpx.Client:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    return httpx.Client(transport=transport, base_url="http://server")


# A checker of hand plays: a violation for an odd profit, and one for a second play
# whose result differs from the first.
def odd_profit_checker(
    agent: str,  # noqa: ARG001
    description: JsonObject,  # noqa: ARG001
    play: Play,
    first: Play | None,
) -> list[str]:
    violations: list[str] = []
    if play.result["profit"] % 2:
        violations.append(f"profit {play.result['profit']} is odd")
    if first is not None and first.result != play.result:
        violations.append("second play differs")
    return violations


# A client that answers the stored play of every run with its profit, no periods and
# an empty description.
def stored_plays_client(profits: dict[str, int]) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        run_id, *route = request.url.path.removeprefix("/runs/").split("/")
        if route == ["result"]:
            return httpx.Response(200, json={"profit": profits[run_id]})
        if route == ["periods"]:
            return httpx.Response(200, json={"periods": []})
        return httpx.Response(200, json={"description": {}})

    transport = httpx.MockTransport(answer)
    return httpx.Client(transport=transport, base_url="http://server")


# Seeds 0 to 2 with every agent, seed 0 played twice.
HAND_WORLD_RUNS = [
    (seed, agent, play)
    for seed in range(3)
    for play in ((1, 2) if seed == 0 else (1,))
    for agent in AGENTS
]


# An exception that its own arguments cannot rebuild, so it does not pass back from a
# process of the pool.
class UnpicklableError(Exception):
    def __init__(self, message: str, *, request: str) -> None:
        super().__init__(f"{message} of {request}")


def raise_unpicklable_error(message: str) -> None:
    raise UnpicklableError(message, request="a request")


def raise_key_error(message: str) -> None:
    raise KeyError(message)


def raise_value_error(message: str) -> None:
    raise ValueError(message)


def raise_invalid_operation(message: str) -> None:
    raise InvalidOperation(message)


def raise_zero_division_error(message: str) -> None:
    raise ZeroDivisionError(message)


def raise_runtime_error(message: str) -> None:
    raise RuntimeError(message)


# The exceptions a hand world can raise in its worker, by name.
RAISES = {
    "UnpicklableError": raise_unpicklable_error,
    "KeyError": raise_key_error,
    "ValueError": raise_value_error,
    "InvalidOperation": raise_invalid_operation,
    "ZeroDivisionError": raise_zero_division_error,
    "RuntimeError": raise_runtime_error,
}
# The text of each of these exceptions raised in a seed.
RAISED_TEXTS = {
    "UnpicklableError": "seed {seed} of a request",
    "KeyError": "'seed {seed}'",
    "ValueError": "seed {seed}",
    "InvalidOperation": "seed {seed}",
    "ZeroDivisionError": "seed {seed}",
    "RuntimeError": "seed {seed}",
}


# A hand world of steady market played by no decisions and the reference; its content
# names the exception it raises in its worker, if any, and the folder where it leaves
# a file named by its seed once it starts.
def raising_world(seed: int, raised: str | None, folder: str = "") -> World:
    content = {"raises": raised, "folder": folder}
    return World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content=content,
        seed=seed,
        replay=False,
        agents=AGENTS[:2],
    )


def hand_rows_of(world: World) -> list[PlayedRun]:
    return [
        hand_run(agent, world.seed, run_id=f"{agent}-{world.seed}")
        for agent in world.agents
    ]


# The play of a hand world in a worker: its rows, or the exception its content names.
def play_hand_world(world: World) -> tuple[list[PlayedRun], list[str]]:
    folder = world.scenario_content["folder"]
    if folder:
        (Path(folder) / str(world.seed)).touch()
        time.sleep(0.2)
    raised = world.scenario_content["raises"]
    if raised is not None:
        RAISES[raised](f"seed {world.seed}")
    return hand_rows_of(world), []


# The play of a hand world whose seed 1 gives no decisions a profit that is no number:
# `indexed_run` raises `ValueError` building its row.
def play_hand_world_of_a_bad_profit(
    world: World,
) -> tuple[list[PlayedRun], list[str]]:
    if world.seed == 1:
        play = Play(
            run_id="no_decisions-1",
            result={"profit": [1], "measures": {}},
            periods=[],
            solves_at_time_limit=0,
        )
        agent_play = AgentPlay(
            agent="no_decisions",
            description={},
            play=play,
            seconds=1.5,
            optimizer=None,
        )
        indexed_run(world, agent_play, 1, [], "time_limit=60.0", "c0de", "c4ec5", "")
    return play_hand_world(world)


# The play of a world that ends its process at once, without an exception.
def end_the_process(world: World) -> tuple[list[PlayedRun], list[str]]:  # noqa: ARG001
    os._exit(1)


SHIP = {"kind": "ship", "quantity": "4"}
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "16"}
MAKE_BOARDS = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "8"}
MAKE_MONITORS = {
    "kind": "produce",
    "line": "line-1",
    "item": "monitor",
    "quantity": "4",
}


# The play of a control of fixed decisions in periods 1 to 5 of 6 of the plain tiny
# factory from a cash and 8 monitors: the outcomes of each of the 5 periods and the
# outcome measures of its result.
def play_control(
    cash: str, decisions: dict[int, list[dict[str, str]]]
) -> tuple[list[list[tuple[str, bool]]], dict[str, Decimal]]:
    scenario = plain_tiny_scenario() | {
        "horizon": 6,
        "start": {"cash": cash, "stock": {"main": {"monitor": "8"}}},
    }
    with benchmark_client() as client:
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        outcomes: list[list[tuple[str, bool]]] = []
        for period in range(1, 6):
            submission = [
                decision | {"order": f"order-{period}-1"}
                if decision["kind"] == "ship"
                else decision
                for decision in decisions.get(period, [])
            ]
            observation = benchmark.send(
                client,
                "POST",
                f"/runs/{run['id']}/decisions",
                {"period": period, "decisions": submission},
            )
            outcomes.append(
                [
                    (outcome["decision"]["kind"], outcome["accepted"])
                    for outcome in observation["outcomes"]
                ]
            )
        benchmark.send(
            client,
            "POST",
            f"/runs/{run['id']}/decisions",
            {"period": 6, "decisions": []},
        )
        result = benchmark.read(client, f"/runs/{run['id']}/result")
    paths = (*OUTCOME_PATHS, "units_lost.total")
    return outcomes, {path: measure_value(result, path) for path in paths}


def test_three_rows_appended_to_the_index_read_back_equal(tmp_path: Path):
    runs = [
        hand_run("no_decisions", profit=Decimal("-114.4")),
        hand_run(
            "reference",
            profit=Decimal(328),
            seconds=0.123456789,
            solves=3,
            solves_at_time_limit=1,
            solves_without_solution=1,
            relaxed_program_value=328.00000000001,
            linear=False,
            largest_gap=0.0085,
            dropped=0,
            fitted=0,
            violations=("decisions rejected: 1", "ended after period 2 of 3"),
            measures=dict.fromkeys(MEASURE_PATHS, Decimal("12.5")),
        ),
        hand_run("full_horizon_optimizer", solves=3, dropped=1, fitted=2, linear=False),
    ]
    index = tmp_path / "stress-runs.csv"
    append_to_index(index, runs[:1])
    append_to_index(index, runs[1:])

    read_runs = read_index(index)
    header = index.read_text().splitlines()[0].split(",")

    assert read_runs == runs
    assert str(read_runs[0].profit) == "-114.4"
    assert header[10:13] == ["solves_without_solution", "dropped", "fitted"]
    assert header[19:23] == ["code", "solver_environment", "checks", "time"]


def test_the_rows_of_a_world_replace_the_index_through_a_new_file(
    tmp_path: Path,
):
    runs = [hand_run(agent) for agent in AGENTS[:3]]
    index = tmp_path / "stress-runs.csv"
    # A stop before the replace leaves half a new file beside the index.
    (tmp_path / "stress-runs.csv.new").write_text("scenario,scen")
    append_to_index(index, runs[:1])
    before = index.stat().st_ino
    append_to_index(index, runs[1:])

    assert read_index(index) == runs
    assert index.stat().st_ino != before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["stress-runs.csv"]


def test_a_row_cut_by_a_stop_is_refused_then_set_aside_beside_the_index(
    tmp_path: Path,
):
    runs = [hand_run(agent) for agent in AGENTS[:3]]
    index = tmp_path / "stress-runs.csv"
    append_to_index(index, runs)
    whole = index.read_bytes()
    cut = whole[: whole.rindex(b"reference")]
    index.write_bytes(cut)

    with pytest.raises(ValueError) as refused:
        read_index(index)
    set_aside_cut_row(index)
    read_runs = read_index(index)
    set_aside_cut_row(index)

    assert str(refused.value) == (
        f"the index {index} ends in a row cut before its line break; set it aside"
    )
    assert read_runs == runs[:1]
    assert (tmp_path / "stress-runs.csv.cut").read_bytes() == (
        cut.split(b"\r\n")[-1] + b"\n"
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "stress-runs.csv",
        "stress-runs.csv.cut",
    ]


def test_a_file_cut_before_its_first_line_break_starts_as_an_empty_index(
    tmp_path: Path,
):
    index = tmp_path / "stress-runs.csv"
    index.write_bytes(b"scenario,scenario_id")

    set_aside_cut_row(index)
    read_runs = read_index(index)
    append_to_index(index, [hand_run("no_decisions")])

    assert read_runs == []
    assert read_index(index) == [hand_run("no_decisions")]
    assert (tmp_path / "stress-runs.csv.cut").read_bytes() == b"scenario,scenario_id\n"


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    st.lists(
        st.integers(-1000, 1000), min_size=3 * len(AGENTS), max_size=3 * len(AGENTS)
    ),
    st.data(),
)
def test_a_stop_after_any_byte_and_a_resume_give_the_rows_of_an_uninterrupted_write(
    drawn: list[int], data: st.DataObject
):
    profits = dict(
        zip(
            [(seed, agent) for seed in range(3) for agent in AGENTS],
            drawn,
            strict=True,
        )
    )
    with tempfile.TemporaryDirectory() as directory:
        index = Path(directory) / "stress-runs.csv"
        for world in HAND_WORLDS:
            append_to_index(index, hand_world_rows(world, profits, "first"))
        uninterrupted = read_index(index)
        text = index.read_bytes()
        index.write_bytes(text[: data.draw(st.integers(0, len(text)))])

        set_aside_cut_row(index)
        left = worlds_left(HAND_IDENTITY, read_index(index), HAND_WORLDS)
        for world in left:
            append_to_index(index, hand_world_rows(world, profits, "again"))
        resumed, violations = unique_runs(read_index(index))
        missing = missing_run_violations(HAND_IDENTITY, resumed, HAND_WORLDS)

    assert (violations, missing) == ([], [])
    assert sorted(
        (replace(run, run_id="") for run in resumed), key=row_key_of
    ) == sorted((replace(run, run_id="") for run in uninterrupted), key=row_key_of)
    assert scores_of(resumed) == scores_of(uninterrupted)


def test_a_row_of_the_myopic_optimizer_appended_to_the_index_reads_back_equal(
    tmp_path: Path,
):
    run = hand_run("myopic_optimizer", solves=3, dropped=0, fitted=0, linear=True)
    index = tmp_path / "stress-runs.csv"
    append_to_index(index, [run])

    read_runs = read_index(index)

    assert read_runs == [run]


def test_a_world_whose_runs_of_every_agent_the_index_holds_is_not_left():
    runs = both_plays(AGENTS)
    worlds = [
        World(
            scenario="steady-market",
            scenario_id="s1",
            manifest_id="m1",
            scenario_content={},
            seed=seed,
            replay=seed == 0,
        )
        for seed in (0, 1)
    ]

    left = worlds_left(HAND_IDENTITY, runs, worlds)
    left_at_30 = worlds_left(
        RunIdentity(
            settings="time_limit=30.0",
            version="0.4.0",
            code="c0de",
            solver_environment=SOLVER_ENVIRONMENT,
        ),
        runs,
        worlds,
    )

    assert [world.seed for world in left] == [1]
    assert [world.seed for world in left_at_30] == [0, 1]
    assert [world.agents for world in left] == [AGENTS]


def test_a_world_played_twice_with_only_its_first_play_is_left_whole():
    runs = [hand_run(agent) for agent in AGENTS]
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    left = worlds_left(HAND_IDENTITY, runs, [world])

    assert left == [world]


def test_a_world_without_the_second_play_of_no_decisions_plays_every_agent():
    runs = [
        run
        for run in both_plays(AGENTS)
        if (run.agent, run.play) != ("no_decisions", 2)
    ]
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    left = worlds_left(HAND_IDENTITY, runs, [world])

    assert left == [world]


def test_a_world_without_one_repeat_plays_that_agent_in_both_plays():
    runs = [
        run
        for run in both_plays(AGENTS)
        if (run.agent, run.play) != ("myopic_optimizer", 2)
    ]
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    left = worlds_left(HAND_IDENTITY, runs, [world])

    assert left == [replace(world, agents=("myopic_optimizer",))]


def test_two_rows_of_one_run_of_a_world_count_once_as_the_later_row():
    earlier = hand_run("rolling_optimizer", run_id="first", seconds=2.0)
    later = hand_run("rolling_optimizer", run_id="second", time="2026-10-13T10:00:00")
    other = hand_run("rolling_optimizer", 1)

    runs, violations = unique_runs([earlier, other, later])

    assert runs == [later, other]
    assert violations == []


def test_two_rows_of_one_run_that_differ_give_a_violation_and_count_the_later_row():
    earlier = hand_run("rolling_optimizer", run_id="first", profit=Decimal(5))
    later = hand_run("rolling_optimizer", run_id="second", profit=Decimal(6))
    timed_out = replace(later, solves_at_time_limit=1)

    runs, violations = unique_runs([earlier, later])
    timed_out_runs, timed_out_violations = unique_runs([earlier, timed_out])

    assert runs == [later]
    assert violations == [
        "steady-market seed 0 rolling_optimizer play 1: the runs first and second "
        "differ in profit"
    ]
    assert (timed_out_runs, timed_out_violations) == ([timed_out], [])


def test_two_rows_of_one_run_that_differ_in_a_measure_give_a_violation_naming_it():
    earlier = hand_run("rolling_optimizer", run_id="first")
    later = hand_run(
        "rolling_optimizer",
        run_id="second",
        measures={**earlier.measures, "units_lost.total": Decimal(5)},
    )

    _, violations = unique_runs([earlier, later])

    assert violations == [
        "steady-market seed 0 rolling_optimizer play 1: the runs first and second "
        "differ in units_lost.total"
    ]


def test_two_rows_of_one_play_under_two_solver_environments_are_two_runs():
    earlier = hand_run("rolling_optimizer", run_id="first", profit=Decimal(5))
    later = hand_run(
        "rolling_optimizer",
        run_id="second",
        profit=Decimal(6),
        solver_environment="scipy=1.19.0, highs=1.13.0",
    )

    runs, violations = unique_runs([earlier, later])

    assert runs == [earlier, later]
    assert violations == []


def test_a_report_of_a_world_without_its_second_play_lists_each_missing_run(
    tmp_path: Path,
):
    runs = [
        run
        for run in both_plays(AGENTS)
        if run.play == 1 or run.agent == "no_decisions"
    ]
    worlds = [
        World(
            scenario="steady-market",
            scenario_id="s1",
            manifest_id="m1",
            scenario_content={},
            seed=0,
            replay=True,
        )
    ]
    provenance = Provenance(
        version="0.4.0",
        code="c0de",
        solver_environment=SOLVER_ENVIRONMENT,
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name="Plain tiny factory",
        manifest_id="m1",
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )

    violations = missing_run_violations(HAND_IDENTITY, runs, worlds)
    complete = missing_run_violations(HAND_IDENTITY, both_plays(AGENTS), worlds)
    report = write_report(
        tmp_path, runs, violations, provenance, datetime(2026, 10, 20)
    )
    section = (report / "report.md").read_text().split("## Violations\n\n")[1]

    assert violations == [
        "steady-market seed 0: the index holds no run of reference play 2, "
        "full_horizon_optimizer play 2, rolling_optimizer play 2, aligned_optimizer "
        "play 2, myopic_optimizer play 2, buffered_rolling_optimizer play 2"
    ]
    assert complete == []
    assert section.startswith(f"- {violations[0]}\n")


def test_a_world_without_the_myopic_optimizer_plays_that_optimizer_only():
    runs = both_plays(tuple(agent for agent in AGENTS if agent != "myopic_optimizer"))
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    left = worlds_left(HAND_IDENTITY, runs, [world])

    assert [world.agents for world in left] == [("myopic_optimizer",)]


def test_a_world_without_the_reference_plays_every_agent_from_no_decisions():
    runs = [hand_run(agent) for agent in AGENTS if agent != "reference"]
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    left = worlds_left(HAND_IDENTITY, runs, [world])

    assert [world.agents for world in left] == [AGENTS]


def test_a_world_whose_runs_the_index_holds_under_another_code_plays_every_agent():
    runs = both_plays(AGENTS)
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )

    other = worlds_left(
        RunIdentity(
            settings="time_limit=60.0",
            version="0.4.0",
            code="other",
            solver_environment=SOLVER_ENVIRONMENT,
        ),
        runs,
        [world],
    )
    own = worlds_left(HAND_IDENTITY, runs, [world])

    assert [world.agents for world in other] == [AGENTS]
    assert own == []


def test_a_world_held_whole_under_another_solver_environment_plays_every_agent():
    runs = both_plays(AGENTS)
    world = World(
        scenario="steady-market",
        scenario_id="s1",
        manifest_id="m1",
        scenario_content={},
        seed=0,
        replay=True,
    )
    current = "scipy=1.19.0, highs=1.13.0"

    own = worlds_left(HAND_IDENTITY, runs, [world])
    identity = RunIdentity(
        settings="time_limit=60.0",
        version="0.4.0",
        code="c0de",
        solver_environment=current,
    )
    other = worlds_left(identity, runs, [world])
    missing = missing_run_violations(identity, runs, [world])

    assert own == []
    assert other == [world]
    assert len(missing) == 1
    assert missing[0].startswith(
        "steady-market seed 0: the index holds no run of no_decisions play 1, "
    )


def test_the_digest_of_the_code_reads_every_python_file_in_the_order_of_its_path(
    tmp_path: Path,
):
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    only_a = build_code_digest(tmp_path)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c.py").write_bytes(b"y = 2\n")
    with_c = build_code_digest(tmp_path)
    (tmp_path / "notes.txt").write_bytes(b"not code")
    with_text = build_code_digest(tmp_path)
    (tmp_path / "b" / "c.py").write_bytes(b"y = 3\n")
    changed = build_code_digest(tmp_path)

    assert only_a == sha256_of(f"{sha256_of('x = 1\n')} a.py\n")
    assert with_c == sha256_of(
        f"{sha256_of('x = 1\n')} a.py\n{sha256_of('y = 2\n')} b/c.py\n"
    )
    assert with_text == with_c
    assert changed != with_c


# The folder lists `b/c.py` before `a.py`, the reverse of the order of their paths.
def test_the_digest_of_the_code_is_the_same_in_any_order_the_folder_lists_its_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c.py").write_bytes(b"y = 2\n")
    listed = sorted(tmp_path.rglob("*.py"), reverse=True)

    def listed_in_reverse(_folder: Path, _pattern: str) -> Iterator[Path]:
        return iter(listed)

    monkeypatch.setattr(Path, "rglob", listed_in_reverse)

    reversed_digest = build_code_digest(tmp_path)

    assert reversed_digest == sha256_of(
        f"{sha256_of('x = 1\n')} a.py\n{sha256_of('y = 2\n')} b/c.py\n"
    )


def test_the_digest_of_the_code_changes_when_a_file_is_renamed_or_code_moves(
    tmp_path: Path,
):
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    (tmp_path / "b.py").write_bytes(b"y = 2\n")
    before = build_code_digest(tmp_path)
    (tmp_path / "b.py").rename(tmp_path / "c.py")
    renamed = build_code_digest(tmp_path)
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")
    (tmp_path / "c.py").write_bytes(b"")
    moved = build_code_digest(tmp_path)

    assert len({before, renamed, moved}) == 3


def test_the_digest_of_the_checks_reads_the_checks_and_the_cost_kinds_they_read(
    tmp_path: Path,
):
    (tmp_path / "stress").mkdir()
    (tmp_path / "factories").mkdir()
    (tmp_path / "stress" / "checks.py").write_bytes(b"x = 1\n")
    (tmp_path / "factories" / "strategies.py").write_bytes(b"y = 2\n")
    both = build_checks_digest(tmp_path)
    (tmp_path / "stress" / "report.py").write_bytes(b"z = 3\n")
    with_report = build_checks_digest(tmp_path)
    (tmp_path / "stress" / "checks.py").write_bytes(b"x = 4\n")
    changed = build_checks_digest(tmp_path)

    assert both == sha256_of(
        f"{sha256_of('x = 1\n')} stress/checks.py\n"
        f"{sha256_of('y = 2\n')} factories/strategies.py\n"
    )
    assert with_report == both
    assert changed == sha256_of(
        f"{sha256_of('x = 4\n')} stress/checks.py\n"
        f"{sha256_of('y = 2\n')} factories/strategies.py\n"
    )


def test_the_solver_environment_names_the_interpreter_the_solver_and_the_platform():
    parts = build_solver_environment().split(", ")

    assert [part.split("=")[0] for part in parts] == [
        "python",
        "numpy",
        "scipy",
        "highs",
        "system",
        "machine",
        "libc",
    ]
    assert parts[0] == f"python=CPython {platform.python_version()}"
    assert parts[1:3] == [f"numpy={version('numpy')}", f"scipy={version('scipy')}"]
    assert re.fullmatch(r"highs=\d+\.\d+\.\d+", parts[3])
    assert parts[4:6] == [
        f"system={platform.system()}",
        f"machine={platform.machine()}",
    ]


@pytest.mark.parametrize("column", ["code", "solver_environment", "checks"])
def test_an_index_without_the_column_code_solver_environment_or_checks_is_refused(
    tmp_path: Path, column: str
):
    index = tmp_path / "stress-runs.csv"
    index.write_text(",".join(name for name in COLUMNS if name != column) + "\n")

    with pytest.raises(ValueError) as refused:
        read_index(index)

    assert str(refused.value) == (
        f"the index {index} has other columns than the stress test writes; move it away"
    )


def test_a_scenario_that_hides_a_group_but_durations_adds_the_two_informed_runs():
    assert agents_of([]) == AGENTS
    assert agents_of(["disruptions.duration"]) == AGENTS
    assert agents_of(["lines.items.yield"]) == (
        *AGENTS,
        "informed_optimizer",
        "buffered_informed_optimizer",
    )
    assert len(AGENTS) == 7


def test_the_settings_name_the_time_limit_and_both_terminal_value_factors():
    assert settings_of(600.0) == (
        "time_limit=600.0, lean_terminal_value_factor=1.01, "
        "buffered_terminal_value_factor=1.2"
    )


@pytest.mark.slow
def test_a_world_of_the_checks_c4ec5_is_checked_again_by_checker_b(
    tmp_path: Path,
):
    with benchmark_client() as client:
        held = stored_world(client)
        checked, missing = rechecked_runs(client, held, "b", checker_b)
    provenance = Provenance(
        version="0.4.0",
        code="c0de",
        solver_environment=SOLVER_ENVIRONMENT,
        checks="b",
        analysis="a7a1",
        time="2026-10-12T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id="m1",
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    report = write_report(tmp_path, checked, [], provenance, datetime(2026, 10, 12))
    lines = (report / "report.md").read_text().splitlines()
    rolling = held[AGENTS.index("rolling_optimizer")]

    assert missing == []
    assert {(run.code, run.checks) for run in checked} == {("c0de", "b")}
    assert [run.profit for run in checked] == [Decimal("-114.4")] * 7
    assert [run.violations for run in checked if run.violations] == [
        ("checker B finds a violation",)
    ]
    assert (
        f"- steady-market seed 0 rolling_optimizer {rolling.run_id}: checker B finds "
        "a violation"
    ) in lines


@pytest.mark.slow
def test_the_current_checks_read_the_stored_plays_once():
    with benchmark_client() as client:
        held = [
            replace(run, violations=("ledger sums to 1, cash changed by 0",))
            for run in stored_world(client)
        ]
        checked, missing = rechecked_runs(client, held, "b", violations_of_play)
    with refusing_client() as refusing:
        again, missing_again = rechecked_runs(
            refusing, checked, "b", violations_of_play
        )

    assert (missing, missing_again) == ([], [])
    assert [(run.checks, run.violations) for run in checked] == [("b", ())] * 7
    assert again == checked


@pytest.mark.slow
def test_a_world_with_a_run_the_server_does_not_hold_keeps_its_rows():
    missing_run_id = "0" * 32
    with benchmark_client() as client:
        held = stored_world(client)
        held[1] = replace(held[1], run_id=missing_run_id)
        checked, missing = rechecked_runs(client, held, "b", violations_of_play)

    assert checked == held
    assert missing == [
        f"steady-market seed 0 reference {missing_run_id}: the stored run cannot be "
        f"read, so the current checks did not run: GET /runs/{missing_run_id}: 404 "
        f"run_id: unknown run {missing_run_id}"
    ]


def test_the_second_play_of_a_stored_world_is_checked_against_its_first_play():
    profits = {f"{agent}-0-{play}": 2 for agent in AGENTS for play in (1, 2)}
    profits["rolling_optimizer-0-2"] = 0
    held = [
        hand_run(agent, play=play, run_id=f"{agent}-0-{play}", checks="a")
        for play in (1, 2)
        for agent in AGENTS
    ]
    with stored_plays_client(profits) as client:
        checked, _ = rechecked_runs(client, held, "b", odd_profit_checker)

    assert [(run.run_id, run.violations) for run in checked if run.violations] == [
        ("rolling_optimizer-0-2", ("second play differs",))
    ]


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(
    st.lists(
        st.tuples(st.integers(0, 3), st.booleans(), st.sampled_from([(), ("old",)])),
        min_size=len(HAND_WORLD_RUNS),
        max_size=len(HAND_WORLD_RUNS),
    )
)
def test_checking_stored_plays_again_gives_the_same_conclusions(
    stored: list[tuple[int, bool, tuple[str, ...]]],
):
    profits = {
        f"{agent}-{seed}-{play}": profit
        for (seed, agent, play), (profit, _, _) in zip(
            HAND_WORLD_RUNS, stored, strict=True
        )
    }
    fresh = [
        hand_run(agent, seed, play=play, run_id=f"{agent}-{seed}-{play}", checks="a")
        for seed, agent, play in HAND_WORLD_RUNS
    ]
    with stored_plays_client(profits) as client:
        expected, _ = rechecked_runs(client, fresh, "b", odd_profit_checker)
        # A row of the current checks holds their conclusions; any other row holds
        # the conclusions of other checks.
        held = [
            replace(run, checks="a", violations=violations) if is_stale else checked
            for run, checked, (_, is_stale, violations) in zip(
                fresh, expected, stored, strict=True
            )
        ]
        once, _ = rechecked_runs(client, held, "b", odd_profit_checker)
        twice, _ = rechecked_runs(client, once, "b", odd_profit_checker)

    assert once == expected
    assert twice == once


def test_a_row_of_another_solver_environment_is_not_checked_again(
    tmp_path: Path,
):
    index = tmp_path / "stress-runs.csv"
    other = hand_run("no_decisions", solver_environment="scipy=1.19.0, highs=1.13.0")
    append_to_index(index, [other])
    with benchmark_client() as client:
        missing = recheck_index(client, index, HAND_IDENTITY, "b", checker_b)

    assert missing == []
    assert read_index(index) == [other]


@pytest.mark.slow
def test_the_index_holds_the_rows_of_its_code_checked_by_the_current_checks(
    tmp_path: Path,
):
    index = tmp_path / "stress-runs.csv"
    other_code = hand_run("no_decisions", 1, code="other")
    with benchmark_client() as client:
        held = stored_world(client)
        append_to_index(index, [other_code, *held])
        missing = recheck_index(client, index, HAND_IDENTITY, "b", checker_b)
    runs = read_index(index)

    assert missing == []
    assert runs[0] == other_code
    assert [run.run_id for run in runs[1:]] == [run.run_id for run in held]
    assert {run.checks for run in runs[1:]} == {"b"}
    assert [run.agent for run in runs if run.violations] == ["rolling_optimizer"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["stress-runs.csv"]


def test_a_world_whose_row_raises_leaves_the_rows_of_the_other_worlds_in_the_index(
    tmp_path: Path,
):
    worlds = [raising_world(seed, None) for seed in range(3)]
    index = tmp_path / "stress-runs.csv"

    violations = play_worlds_in_pool(play_hand_world_of_a_bad_profit, worlds, 2, index)

    assert sorted(read_index(index), key=row_key_of) == sorted(
        hand_rows_of(worlds[0]) + hand_rows_of(worlds[2]), key=row_key_of
    )
    assert violations == [
        "steady-market seed 1: ValueError: argument must be a sequence of length 3"
    ]


@pytest.mark.property
@settings(max_examples=example_count(20))
@given(
    st.lists(st.sampled_from([None, *RAISES]), min_size=1, max_size=5),
    st.integers(1, 3),
)
def test_the_index_holds_the_worlds_that_end_and_the_session_names_each_that_raises(
    raised: list[str | None], workers: int
):
    worlds = [raising_world(seed, name) for seed, name in enumerate(raised)]
    with tempfile.TemporaryDirectory() as directory:
        index = Path(directory) / "stress-runs.csv"
        violations = play_worlds_in_pool(play_hand_world, worlds, workers, index)
        held = read_index(index)

    ended = [world for world in worlds if world.scenario_content["raises"] is None]
    failed = [world for world in worlds if world not in ended]
    assert sorted(held, key=row_key_of) == sorted(
        (run for world in ended for run in hand_rows_of(world)), key=row_key_of
    )
    assert sorted(violations) == sorted(
        f"steady-market seed {world.seed}: {world.scenario_content['raises']}: "
        + RAISED_TEXTS[world.scenario_content["raises"]].format(seed=world.seed)
        for world in failed
    )


@pytest.mark.slow
def test_a_worker_that_ends_abruptly_fails_its_world_with_the_broken_pool(
    tmp_path: Path,
):
    index = tmp_path / "stress-runs.csv"

    violations = play_worlds_in_pool(
        end_the_process, [raising_world(0, None)], 1, index
    )

    assert violations == [
        "steady-market seed 0: BrokenProcessPool: A process in the process pool was "
        "terminated abruptly while the future was running or pending."
    ]
    assert not index.exists()


@pytest.mark.slow
def test_a_session_that_cannot_write_its_index_stops_its_queued_worlds(
    tmp_path: Path,
):
    started = tmp_path / "started"
    started.mkdir()
    worlds = [raising_world(seed, None, str(started)) for seed in range(8)]
    index = tmp_path / "stress-runs.csv"
    index.mkdir()

    with pytest.raises(IsADirectoryError):
        play_worlds_in_pool(play_hand_world, worlds, 1, index)

    assert len(list(started.iterdir())) <= 3


@pytest.mark.slow
def test_two_worlds_of_the_plain_tiny_factory_play_in_two_workers_and_resume(
    tmp_path: Path,
):
    folder = tmp_path
    index = folder / "records" / "stress-runs.csv"
    database = folder / "records" / "stress.duckdb"
    with (
        started_server(database) as url,
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
        violations = play_worlds(url, worlds, 2, 60.0, "c0de", "c4ec5", index)
        runs = read_index(index)
        statuses = {client.get(f"/runs/{run.run_id}").status_code for run in runs}
    provenance = Provenance(
        version=version("factory-simulator"),
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-12T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(2),
        protocol="development",
        settings="time_limit=60.0",
    )
    report = write_report(
        folder / "reports", runs, violations, provenance, datetime(2026, 10, 12)
    )
    lines = (report / "report.md").read_text().splitlines()
    left = worlds_left(
        RunIdentity(
            settings=settings_of(60.0),
            version=version("factory-simulator"),
            code="c0de",
            solver_environment=build_solver_environment(),
        ),
        runs,
        worlds,
    )

    assert violations == []
    assert [message for run in runs for message in run.violations] == []
    assert len(runs) == 21
    assert {(run.code, run.checks) for run in runs} == {("c0de", "c4ec5")}
    assert statuses == {200}
    # The reference of the plain tiny factory drops and fits nothing.
    assert {
        (run.agent, run.dropped, run.fitted)
        for run in runs
        if run.agent in ("no_decisions", "reference")
    } == {("no_decisions", None, None), ("reference", 0, 0)}
    # (328 - -114.4) / 442.4 = 1 and (-114.4 - -114.4) / 442.4 = 0 in both seeds. The
    # credit choice of the buy of the first period makes every program integer, and
    # every solve stops at the gap limit with a gap of 0.
    assert (
        "| Plain tiny scenario | full_horizon_optimizer | integer | 2 | 1.000 | 1.000 "
        "| 1.000 | 1.000 | 0.0000 |"
    ) in lines
    assert (
        "| Plain tiny scenario | aligned_optimizer | integer | 2 | 0.000 | 0.000 "
        "| 0.000 | 0.000 | 0.0000 |"
    ) in lines
    assert left == []


# The plain tiny world of seed 0 played once, its rows then marked with an earlier
# solver environment, and resumed under the current one.
@pytest.mark.slow
def test_a_world_resumed_under_another_solver_environment_reports_its_new_runs_only(
    tmp_path: Path,
):
    index = tmp_path / "records" / "stress-runs.csv"
    package_version = version("factory-simulator")
    settings = settings_of(60.0)
    current = build_solver_environment()
    with started_server(tmp_path / "records" / "stress.duckdb") as url:
        with httpx.Client(base_url=url) as client:
            stored_manifest = benchmark.send(
                client, "POST", "/manifests", plain_tiny_manifest()
            )
            path = f"/manifests/{stored_manifest['id']}/scenarios"
            scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        world = World(
            scenario=plain_tiny_scenario()["name"],
            scenario_id=scenario["id"],
            manifest_id=stored_manifest["id"],
            scenario_content=plain_tiny_scenario(),
            seed=0,
            replay=False,
        )
        play_worlds(url, [world], 1, 60.0, "c0de", "c4ec5", index)
        earlier = [
            replace(run, solver_environment="scipy=1.17.0, highs=1.11.0")
            for run in read_index(index)
        ]
        index.unlink()
        append_to_index(index, earlier)
        identity = RunIdentity(
            settings=settings,
            version=package_version,
            code="c0de",
            solver_environment=current,
        )
        left = worlds_left(identity, read_index(index), [world])
        violations = play_worlds(url, left, 1, 60.0, "c0de", "c4ec5", index)
    held = read_index(index)
    runs, differing = unique_runs(current_runs(identity, held, [world]))
    provenance = Provenance(
        version=package_version,
        code="c0de",
        solver_environment=current,
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings=settings,
    )
    report = write_report(
        tmp_path / "reports", runs, differing, provenance, datetime(2026, 10, 20)
    )
    text = (report / "report.md").read_text()
    with (report / "runs.csv").open(newline="") as file:
        reported = list(csv.DictReader(file))
    with pytest.raises(ValueError) as refused:
        write_report(
            tmp_path / "reports", held, [], provenance, datetime(2026, 10, 20, 1)
        )

    assert left == [world]
    assert violations == []
    assert held[:7] == earlier
    assert (runs, differing) == (held[7:], [])
    assert f"- Solver environment: {current}" in text.splitlines()
    assert {row["solver_environment"] for row in reported} == {current}
    assert [row["run_id"] for row in reported] == [run.run_id for run in held[7:]]
    assert str(refused.value).startswith(
        "the runs hold rows of a solver environment other than "
    )


# A stop of a write that is not whole leaves the header, the rows of no decisions, the
# reference and the full-horizon optimizer of play 1, and half the next row.
@pytest.mark.slow
def test_a_world_resumed_from_a_readable_prefix_counts_each_run_once(
    tmp_path: Path,
):
    index = tmp_path / "records" / "stress-runs.csv"
    database = tmp_path / "records" / "stress.duckdb"
    package_version = version("factory-simulator")
    settings = settings_of(60.0)
    with (
        started_server(database) as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        world = World(
            scenario=plain_tiny_scenario()["name"],
            scenario_id=scenario["id"],
            manifest_id=stored_manifest["id"],
            scenario_content=plain_tiny_scenario(),
            seed=0,
            replay=True,
        )
        play_worlds(url, [world], 1, 60.0, "c0de", "c4ec5", index)
        lines = index.read_bytes().split(b"\r\n")
        index.write_bytes(b"\r\n".join(lines[:4]) + b"\r\n" + lines[4][:40])
        set_aside_cut_row(index)
        prefix = read_index(index)
        identity = RunIdentity(
            settings=settings,
            version=package_version,
            code="c0de",
            solver_environment=build_solver_environment(),
        )
        left = worlds_left(identity, prefix, [world])
        violations = play_worlds(url, left, 1, 60.0, "c0de", "c4ec5", index)
        held = read_index(index)
        statuses = {client.get(f"/runs/{run.run_id}").status_code for run in held}
    runs, differing = unique_runs(held)
    provenance = Provenance(
        version=package_version,
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings=settings,
    )
    report = write_report(
        tmp_path / "reports", runs, differing, provenance, datetime(2026, 10, 20)
    )
    text = (report / "report.md").read_text()
    with (report / "runs.csv").open(newline="") as file:
        reported = list(csv.DictReader(file))

    assert [run.agent for run in prefix] == list(AGENTS[:3])
    assert left == [world]
    assert violations == []
    assert len(held) == 17
    assert statuses == {200}
    assert held[:3] == prefix
    assert (differing, len(runs)) == ([], 14)
    assert missing_run_violations(identity, runs, [world]) == []
    assert [row["run_id"] for row in reported] == [run.run_id for run in runs]
    # Each first-play run of seed 0 counts once: 1 world scored.
    assert (
        "| Plain tiny scenario | full_horizon_optimizer | integer | 1 | 1.000 | 1.000 "
        "| 1.000 | 1.000 | 0.0000 |"
    ) in text.splitlines()
    assert "## Violations\n\nNone." in text
    assert (tmp_path / "records" / "stress-runs.csv.cut").read_bytes() == (
        lines[4][:40] + b"\n"
    )


# A world played under the checks `a`, then resumed after a change of the checks alone:
# checker B reads its stored plays, finds a violation of the rolling optimizer and plays
# no run again.
@pytest.mark.slow
def test_a_resumed_world_after_a_change_of_the_checks_is_checked_without_a_play(
    tmp_path: Path,
):
    index = tmp_path / "records" / "stress-runs.csv"
    database = tmp_path / "records" / "stress.duckdb"
    package_version = version("factory-simulator")
    settings = settings_of(60.0)
    with (
        started_server(database) as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        world = World(
            scenario=plain_tiny_scenario()["name"],
            scenario_id=scenario["id"],
            manifest_id=stored_manifest["id"],
            scenario_content=plain_tiny_scenario(),
            seed=1,
            replay=False,
        )
        played = play_worlds(url, [world], 1, 60.0, "c0de", "a", index)
        identity = RunIdentity(
            settings=settings,
            version=package_version,
            code="c0de",
            solver_environment=build_solver_environment(),
        )
        missing = recheck_index(client, index, identity, "b", checker_b)
        left = worlds_left(identity, read_index(index), [world])
        replayed = play_worlds(url, left, 1, 60.0, "c0de", "b", index)
    runs = read_index(index)
    with duckdb.connect(str(database)) as connection:
        recorded = connection.execute("SELECT count(*) FROM runs").fetchone()
    provenance = Provenance(
        version=package_version,
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="b",
        analysis="a7a1",
        time="2026-10-19T10:00:00",
        command="tests/stress",
        manifest_name=plain_tiny_manifest()["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1, 2),
        protocol="development",
        settings=settings,
    )
    report = write_report(
        tmp_path / "reports", runs, missing, provenance, datetime(2026, 10, 19)
    )
    lines = (report / "report.md").read_text().splitlines()
    rolling = next(run for run in runs if run.agent == "rolling_optimizer")

    assert (played, missing, left, replayed) == ([], [], [], [])
    assert recorded == (7,)
    assert len(runs) == 7
    assert {run.checks for run in runs} == {"b"}
    assert "- Checks: b" in lines
    assert (
        f"- Plain tiny scenario seed 1 rolling_optimizer {rolling.run_id}: checker B "
        "finds a violation"
    ) in lines


@pytest.mark.slow
def test_a_world_of_6_agents_in_the_index_plays_the_myopic_optimizer_only(
    tmp_path: Path,
):
    index = tmp_path / "records" / "stress-runs.csv"
    database = tmp_path / "records" / "stress.duckdb"
    package_version = version("factory-simulator")
    with (
        started_server(database) as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        held = [
            hand_run(
                agent,
                scenario_id=scenario["id"],
                version=package_version,
                solver_environment=build_solver_environment(),
            )
            for agent in AGENTS
            if agent != "myopic_optimizer"
        ]
        append_to_index(index, held)
        world = World(
            scenario=plain_tiny_scenario()["name"],
            scenario_id=scenario["id"],
            manifest_id=stored_manifest["id"],
            scenario_content=plain_tiny_scenario(),
            seed=0,
            replay=False,
        )
        left = worlds_left(
            RunIdentity(
                settings="time_limit=60.0",
                version=package_version,
                code="c0de",
                solver_environment=held[0].solver_environment,
            ),
            held,
            [world],
        )
        violations = play_worlds(url, left, 1, 60.0, "c0de", "c4ec5", index)
    runs = read_index(index)
    with duckdb.connect(str(database)) as connection:
        recorded = connection.execute("SELECT count(*) FROM runs").fetchone()

    assert violations == []
    assert runs[:6] == held
    assert [(run.agent, run.violations) for run in runs[6:]] == [
        ("myopic_optimizer", ())
    ]
    assert recorded == (1,)


@pytest.mark.slow
def test_a_world_that_hides_a_yield_plays_the_informed_optimizer_at_both_factors(
    tmp_path: Path,
):
    index = tmp_path / "records" / "stress-runs.csv"
    database = tmp_path / "records" / "stress.duckdb"
    manifest, scenario = hidden_yield_bodies()
    with (
        started_server(database) as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
            agents=agents_of(scenario["hidden"]),
        )
        violations = play_worlds(url, [world], 1, 60.0, "c0de", "c4ec5", index)
    runs = read_index(index)
    with duckdb.connect(str(database)) as connection:
        recorded = connection.execute(
            "SELECT scenario_id = ?, count(*) FROM runs GROUP BY 1 ORDER BY 1",
            [scenario_id],
        ).fetchall()

    assert violations == []
    assert [message for run in runs for message in run.violations] == []
    assert len(runs) == 9
    assert [run.agent for run in runs[-2:]] == [
        "informed_optimizer",
        "buffered_informed_optimizer",
    ]
    assert {run.code for run in runs} == {"c0de"}
    assert recorded == [(False, 2), (True, 9)]


@pytest.mark.slow
def test_the_server_keeps_a_connection_idle_longer_than_the_client_does(
    tmp_path: Path,
):
    with started_server(tmp_path / "keep-alive.duckdb") as url:
        address = urlsplit(url)
        connection = http.client.HTTPConnection(address.hostname or "", address.port)
        connection.request("GET", f"{address.path}/manifests")
        first = connection.getresponse()
        first.read()
        time.sleep(6)
        connection.request("GET", f"{address.path}/manifests")
        second = connection.getresponse()
        second.read()
        connection.close()

    assert (first.status, second.status) == (200, 200)


# Demand is 4 monitors a period at 50, paid at once, less 1 of transport, and lost at
# the end of its period; credit 0. From -300 the shipment of period 1 brings cash to
# -104, below the cost 8 of 16 chips, so the buy is refused and the period closes below
# 0; in period 2 the second shipment brings it to 92 and the buy passes, 84. The chips
# make 8 boards in period 3 and 4 monitors in period 4, shipped in period 5; the making
# costs 8 and 8 and the lost sales of periods 3 and 4 cost 40 each, so period 4 closes
# at -12: 12 of 24 units shipped, 12 lost, 16 bought, 2 periods below the credit limit.
# From -1000 the stock sale reaches -804 and -608, every buy is refused, and the lost
# sales of 4 periods at 40 each keep every close below 0: 8 shipped, 16 lost, 0 bought,
# 6 periods below the credit limit.
@pytest.mark.slow
def test_the_outcomes_of_a_run_tell_a_recovery_from_a_liquidation():
    recovery = {
        1: [SHIP, BUY],
        2: [SHIP, BUY],
        3: [MAKE_BOARDS],
        4: [MAKE_MONITORS],
        5: [SHIP],
    }
    liquidation = {1: [SHIP, BUY], 2: [SHIP, BUY], 3: [BUY], 4: [BUY], 5: [BUY]}

    recovered, recovery_outcomes = play_control("-300", recovery)
    liquidated, liquidation_outcomes = play_control("-1000", liquidation)

    assert recovered == [
        [("ship", True), ("buy", False)],
        [("ship", True), ("buy", True)],
        [("produce", True)],
        [("produce", True)],
        [("ship", True)],
    ]
    assert recovery_outcomes == {
        "units_ordered.total": 24,
        "units_shipped.total": 12,
        "units_ordered_from_suppliers.suppliers": 16,
        "periods_below_credit_limit.total": 2,
        "units_lost.total": 12,
    }
    assert liquidated == [
        [("ship", True), ("buy", False)],
        [("ship", True), ("buy", False)],
        [("buy", False)],
        [("buy", False)],
        [("buy", False)],
    ]
    assert liquidation_outcomes == {
        "units_ordered.total": 24,
        "units_shipped.total": 8,
        "units_ordered_from_suppliers.suppliers": 0,
        "periods_below_credit_limit.total": 6,
        "units_lost.total": 16,
    }
