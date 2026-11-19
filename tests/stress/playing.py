import csv
import hashlib
import importlib
import io
import multiprocessing
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import Decimal
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx2 as httpx
import numpy
import scipy
from factories import free_port, play_no_decisions, start_reference, wait_until_ready

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.aligned import aligned_optimizer
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.optimizers.full_horizon import full_horizon_optimizer
from factory_simulator.benchmark.optimizers.informed import informed_optimizer
from factory_simulator.benchmark.optimizers.myopic import myopic_optimizer
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.expected_source import (
    BUFFERED_TERMINAL_VALUE_FACTOR,
    LEAN_TERMINAL_VALUE_FACTOR,
)
from stress.checks import JsonObject, Play, violations_of_play

# The checks of a play: the agent, the description and the play of a run, and the first
# play of its world for a second play, give the messages of the checks it fails.
type PlayChecks = Callable[[str, JsonObject, Play, Play | None], list[str]]
# The columns that differ between two runs of one key that repeat exactly.
RUN_COLUMNS = ("run_id", "seconds", "time")
AGENTS = (
    "no_decisions",
    "reference",
    "full_horizon_optimizer",
    "rolling_optimizer",
    "aligned_optimizer",
    "myopic_optimizer",
    "buffered_rolling_optimizer",
)
# The five limited optimizers.
LIMITED_OPTIMIZERS = AGENTS[2:]
# The limited optimizers whose runs a named measure reads, and the same with the
# reference.
MEASURED_LIMITED_OPTIMIZERS = (
    "full_horizon_optimizer",
    "rolling_optimizer",
    "aligned_optimizer",
)
MEASURED_OPTIMIZERS = ("reference", *MEASURED_LIMITED_OPTIMIZERS)
# The two runs of the informed optimizer, each with its terminal value factor.
INFORMED_FACTORS = {
    "informed_optimizer": LEAN_TERMINAL_VALUE_FACTOR,
    "buffered_informed_optimizer": BUFFERED_TERMINAL_VALUE_FACTOR,
}
INFORMED_AGENTS = tuple(INFORMED_FACTORS)
ROLLING_OPTIMIZER = ("rolling_optimizer",)
# The named measure of each scenario of the library, the direction it takes against
# `steady-market` with the same seed and the agents whose runs it is measured in.
# A count of units lost leaves out the reference: it loses none in `steady-market`.
# No measure is read in the runs of the myopic optimizer.
NAMED_MEASURES = {
    "seasonal-demand": (
        "units_transferred.routes.main-plant/distribution-centre",
        "rises",
        MEASURED_OPTIMIZERS,
    ),
    "growth": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "decline": ("units_lost.total", "falls", MEASURED_LIMITED_OPTIMIZERS),
    "demand-surge": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "demand-step": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "product-life-cycle": (
        "units_lost.products.sensor-gateway",
        "falls",
        MEASURED_LIMITED_OPTIMIZERS,
    ),
    "supplier-outage": (
        "units_arrived.suppliers.apac-chips/microchip",
        "falls",
        MEASURED_OPTIMIZERS,
    ),
    "transport-delays": ("units_arrived_late.suppliers", "rises", MEASURED_OPTIMIZERS),
    "quality-crisis": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "material-shortage": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "price-change": ("material_payment.total", "rises", MEASURED_OPTIMIZERS),
    "line-breakdown": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "frequent-breakdowns": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "capacity-cut": ("units_started.lines.smt-line", "falls", MEASURED_OPTIMIZERS),
    "yield-drop": ("units_scrap.lines.smt-line", "rises", MEASURED_OPTIMIZERS),
    "cash-squeeze": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "full-warehouse": ("units_shipped_late.total", "rises", MEASURED_OPTIMIZERS),
    "forecasts": ("units_lost.total", "falls", ROLLING_OPTIMIZER),
    "notice": (
        "units_arrived.suppliers.apac-chips/microchip",
        "falls",
        MEASURED_OPTIMIZERS,
    ),
    "hidden-groups": ("profit_so_far.total", "falls", ROLLING_OPTIMIZER),
    "regional-crisis": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
    "surge-and-breakdown": ("units_lost.total", "rises", MEASURED_LIMITED_OPTIMIZERS),
}
# The outcomes of every run that the decision value of the report reads beside the
# named measures: the units ordered and shipped of the fill rate, the units bought and
# the periods that close below the credit limit.
OUTCOME_PATHS = (
    "units_ordered.total",
    "units_shipped.total",
    "units_ordered_from_suppliers.suppliers",
    "periods_below_credit_limit.total",
)
MEASURE_PATHS = tuple(
    dict.fromkeys([*(path for path, _, _ in NAMED_MEASURES.values()), *OUTCOME_PATHS])
)
# The constructor of each limited optimizer.
LIMITED_CONSTRUCTORS = {
    "full_horizon_optimizer": full_horizon_optimizer,
    "rolling_optimizer": rolling_optimizer,
    "aligned_optimizer": aligned_optimizer,
    "myopic_optimizer": myopic_optimizer,
    "buffered_rolling_optimizer": buffered_rolling_optimizer,
}


# The agents of a world of a scenario: every agent, and the two informed runs when the
# scenario hides a group other than the duration of disruptions.
def agents_of(hidden: list[str]) -> tuple[str, ...]:
    if any(group != "disruptions.duration" for group in hidden):
        return (*AGENTS, *INFORMED_AGENTS)
    return AGENTS


# One scenario of the manifest and one seed, with the content of the scenario file;
# `agents` are the agents it plays, in order, and `replay` plays them twice.
@dataclass(frozen=True, slots=True, kw_only=True)
class World:
    scenario: str
    scenario_id: str
    manifest_id: str
    scenario_content: dict[str, Any]
    seed: int
    replay: bool
    agents: tuple[str, ...] = AGENTS


# One row of the index: one run of a complete world.
@dataclass(frozen=True, slots=True, kw_only=True)
class PlayedRun:
    scenario: str
    scenario_id: str
    seed: int
    agent: str
    play: int
    run_id: str
    profit: Decimal
    seconds: float
    solves: int
    solves_at_time_limit: int
    solves_without_solution: int
    dropped: int | None
    fitted: int | None
    relaxed_program_value: float | None
    linear: bool | None
    largest_gap: float | None
    violations: tuple[str, ...]
    settings: str
    version: str
    code: str
    solver_environment: str
    checks: str
    time: str
    measures: dict[str, Decimal]


# The play of a world in a process of the pool: its rows, or none and the violations of
# the exception that ended it.
type WorldPlay = Callable[[World], tuple[list[PlayedRun], list[str]]]


# An exception of one agent of a world, named by the agent.
class WorldError(Exception):
    pass


COLUMNS = (
    *(field.name for field in fields(PlayedRun) if field.name != "measures"),
    *MEASURE_PATHS,
)


# What a row of the index is played under: the settings, the version, the code and the
# solver environment. A session and a report read only the rows of the current one.
@dataclass(frozen=True, slots=True, kw_only=True)
class RunIdentity:
    settings: str
    version: str
    code: str
    solver_environment: str


def identity_of(run: PlayedRun) -> RunIdentity:
    return RunIdentity(
        settings=run.settings,
        version=run.version,
        code=run.code,
        solver_environment=run.solver_environment,
    )


# The key of a row: two rows of one key hold two runs of the same play of an agent in
# one world under the same identity.
type RowKey = tuple[str, int, str, int, RunIdentity]


# The value of a measure path in a result: `<name>.total`, `<name>.<kind>.<object>`, or
# `<name>.<kind>`, the sum over every object of the kind; a missing object counts 0.
def measure_value(result: dict[str, Any], path: str) -> Decimal:
    name, kind, *named_object = path.split(".", 2)
    measures = result["measures"].get(kind, {})
    if kind == "total":
        return Decimal(measures.get(name, 0))
    if named_object:
        return Decimal(measures.get(named_object[0], {}).get(name, 0))
    return sum(
        (Decimal(values.get(name, 0)) for values in measures.values()), Decimal(0)
    )


def text_of(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def row_of(run: PlayedRun) -> dict[str, str]:
    row = {
        name: text_of(getattr(run, name))
        for name in COLUMNS
        if name not in MEASURE_PATHS
    }
    row["violations"] = " | ".join(run.violations)
    return row | {path: str(run.measures[path]) for path in MEASURE_PATHS}


def optional_int(text: str) -> int | None:
    return None if text == "" else int(text)


def optional_float(text: str) -> float | None:
    return None if text == "" else float(text)


def run_of(row: dict[str, str]) -> PlayedRun:
    return PlayedRun(
        scenario=row["scenario"],
        scenario_id=row["scenario_id"],
        seed=int(row["seed"]),
        agent=row["agent"],
        play=int(row["play"]),
        run_id=row["run_id"],
        profit=Decimal(row["profit"]),
        seconds=float(row["seconds"]),
        solves=int(row["solves"]),
        solves_at_time_limit=int(row["solves_at_time_limit"]),
        solves_without_solution=int(row["solves_without_solution"]),
        dropped=optional_int(row["dropped"]),
        fitted=optional_int(row["fitted"]),
        relaxed_program_value=optional_float(row["relaxed_program_value"]),
        linear=None if row["linear"] == "" else row["linear"] == "true",
        largest_gap=optional_float(row["largest_gap"]),
        violations=tuple(row["violations"].split(" | ")) if row["violations"] else (),
        settings=row["settings"],
        version=row["version"],
        code=row["code"],
        solver_environment=row["solver_environment"],
        checks=row["checks"],
        time=row["time"],
        measures={path: Decimal(row[path]) for path in MEASURE_PATHS},
    )


# Every run of the index, none when it does not exist yet or is empty; an index of
# other columns, or whose last row a stop cut before its line break, is refused.
def read_index(path: Path) -> list[PlayedRun]:
    if not path.exists():
        return []
    with path.open(newline="") as index:
        text = index.read()
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(
            f"the index {path} has other columns than the stress test writes; "
            "move it away"
        )
    if not text.endswith("\n"):
        raise ValueError(
            f"the index {path} ends in a row cut before its line break; set it aside"
        )
    return [run_of(row) for row in reader]


# The setting aside of the last row of the index when a stop cut it before its line
# break: the row goes, with a line break, to the file `<index>.cut` beside the index,
# the index keeps its text up to its last line break and a line prints where the row
# went. A file without a line break, a header cut by a stop, is set aside whole and
# leaves an empty index.
def set_aside_cut_row(path: Path) -> None:
    if not path.exists():
        return
    whole, line_break, cut = path.read_bytes().rpartition(b"\n")
    if not cut:
        return
    aside = path.with_name(f"{path.name}.cut")
    with aside.open("ab") as file:
        file.write(cut + b"\n")
    new = path.with_name(f"{path.name}.new")
    new.write_bytes(whole + line_break)
    new.replace(path)
    print(f"a row of the index cut by a stop is set aside in {aside}", flush=True)


# The replacement of the index with the runs through a new file beside it, so a stop
# never leaves half an index.
def write_index(path: Path, runs: list[PlayedRun]) -> None:
    new = path.with_name(f"{path.name}.new")
    with new.open("w", newline="") as index:
        writer = csv.DictWriter(index, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(row_of(run) for run in runs)
    new.replace(path)


# The append of the runs of a world to the index, all of them or none: the index is
# replaced with its rows and the runs.
def append_to_index(path: Path, runs: list[PlayedRun]) -> None:
    write_index(path, [*read_index(path), *runs])


# The plays of a world whose runs the index does not hold under an identity, each as
# its agent and play: play 1 of every agent, and play 2 of every agent when the world
# is played twice.
def missing_plays(
    identity: RunIdentity, runs: list[PlayedRun], world: World
) -> list[tuple[str, int]]:
    held = {
        (run.agent, run.play)
        for run in runs
        if (run.scenario_id, run.seed, identity_of(run))
        == (world.scenario_id, world.seed, identity)
    }
    numbers = (1, 2) if world.replay else (1,)
    return [
        (agent, number)
        for number in numbers
        for agent in world.agents
        if (agent, number) not in held
    ]


# The worlds the index does not hold whole, each with the agents it plays: an agent
# with a missing play plays every play of the world again. A world that misses a play
# of no decisions or of the reference plays all its agents.
def worlds_left(
    identity: RunIdentity, runs: list[PlayedRun], worlds: list[World]
) -> list[World]:
    left: list[World] = []
    for world in worlds:
        missing_agents = {agent for agent, _ in missing_plays(identity, runs, world)}
        missing = tuple(agent for agent in world.agents if agent in missing_agents)
        if "no_decisions" in missing or "reference" in missing:
            missing = world.agents
        if missing:
            left.append(replace(world, agents=missing))
    return left


# A violation for every world the index does not hold whole, with its missing plays.
def missing_run_violations(
    identity: RunIdentity, runs: list[PlayedRun], worlds: list[World]
) -> list[str]:
    violations: list[str] = []
    for world in worlds:
        missing = missing_plays(identity, runs, world)
        if missing:
            plays = ", ".join(f"{agent} play {number}" for agent, number in missing)
            violations.append(
                f"{world.scenario} seed {world.seed}: the index holds no run of {plays}"
            )
    return violations


# The runs of the worlds under an identity, in the order of the runs: the rows a
# report of the worlds reads.
def current_runs(
    identity: RunIdentity, runs: list[PlayedRun], worlds: list[World]
) -> list[PlayedRun]:
    keys = {(world.scenario_id, world.seed) for world in worlds}
    return [
        run
        for run in runs
        if (run.scenario_id, run.seed) in keys and identity_of(run) == identity
    ]


def row_key_of(run: PlayedRun) -> RowKey:
    return (run.scenario_id, run.seed, run.agent, run.play, identity_of(run))


# The value of a column of the index in a run: a field, or the value of a measure path.
def column_value(run: PlayedRun, column: str) -> object:
    if column in MEASURE_PATHS:
        return run.measures[column]
    return getattr(run, column)


# The runs with one row of each key, the last row of the key in the order of the runs,
# placed where its first row stands; and a violation for every earlier row that
# differs from the last in a column other than `RUN_COLUMNS`, naming those columns in
# the order of the index, unless one of the two has a solve at the time limit.
def unique_runs(runs: list[PlayedRun]) -> tuple[list[PlayedRun], list[str]]:
    rows: dict[RowKey, list[PlayedRun]] = {}
    for run in runs:
        rows.setdefault(row_key_of(run), []).append(run)
    violations: list[str] = []
    for *earlier, last in rows.values():
        for run in earlier:
            columns = [
                column
                for column in COLUMNS
                if column not in RUN_COLUMNS
                and column_value(run, column) != column_value(last, column)
            ]
            if columns and not (run.solves_at_time_limit or last.solves_at_time_limit):
                violations.append(
                    f"{last.scenario} seed {last.seed} {last.agent} play {last.play}: "
                    f"the runs {run.run_id} and {last.run_id} differ in "
                    + ", ".join(columns)
                )
    return [same[-1] for same in rows.values()], violations


def settings_of(time_limit: float) -> str:
    return (
        f"time_limit={time_limit}, "
        f"lean_terminal_value_factor={LEAN_TERMINAL_VALUE_FACTOR}, "
        f"buffered_terminal_value_factor={BUFFERED_TERMINAL_VALUE_FACTOR}"
    )


# The SHA-256 of files under a folder, each with its path relative to the folder: of
# the text of one line `<SHA-256 hex of the bytes of the file> <path>` per file, in the
# order of the paths given, so a renamed file or code moved to another file changes it.
def build_files_digest(folder: Path, paths: list[str]) -> str:
    lines = [
        f"{hashlib.sha256((folder / path).read_bytes()).hexdigest()} {path}\n"
        for path in paths
    ]
    return hashlib.sha256("".join(lines).encode()).hexdigest()


# The digest of every Python file under a folder, in the order of their paths relative
# to it.
def build_code_digest(folder: Path) -> str:
    paths = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*.py"))
    return build_files_digest(folder, paths)


# The digest of the checks of a run under a folder of tests, then of the module of the
# cost kinds they read.
def build_checks_digest(tests: Path) -> str:
    return build_files_digest(tests, ["stress/checks.py", "factories/strategies.py"])


# The solver environment of this process: the interpreter, numpy, scipy and the HiGHS
# that scipy holds, and the system, machine and C library they run on.
def build_solver_environment() -> str:
    highs = importlib.import_module("scipy.optimize._highspy._core")
    highs_version = (
        f"{highs.HIGHS_VERSION_MAJOR}.{highs.HIGHS_VERSION_MINOR}."
        f"{highs.HIGHS_VERSION_PATCH}"
    )
    libc = " ".join(part for part in platform.libc_ver() if part)
    return (
        f"python={platform.python_implementation()} {platform.python_version()}, "
        f"numpy={numpy.__version__}, scipy={scipy.__version__}, "
        f"highs={highs_version}, system={platform.system()}, "
        f"machine={platform.machine()}, libc={libc}"
    )


# A server of the HTTP interface on a free port and a database file, killed on exit;
# gives the base URL of its routes. It keeps an idle connection 30 s, longer than the 5
# s after which a client drops it, so a client never sends on a connection the server
# is closing.
@contextmanager
def started_server(database: Path) -> Generator[str]:
    database.parent.mkdir(parents=True, exist_ok=True)
    port = free_port()
    environment = os.environ | {
        "FACTORY_SIMULATOR_DATABASE_URL": f"duckdb:///{database}"
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "factory_simulator.api.main:app",
            "--app-dir",
            str(Path(__file__).parents[2] / "src"),
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--timeout-keep-alive",
            "30",
        ],
        env=environment,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            wait_until_ready(client)
        yield f"http://127.0.0.1:{port}/api/v1"
    finally:
        server.kill()
        server.wait()


# One agent played on a new run of a world: the play, its seconds and the optimizer,
# None for no decisions.
@dataclass(frozen=True, slots=True, kw_only=True)
class AgentPlay:
    agent: str
    description: dict[str, Any]
    play: Play
    seconds: float
    optimizer: Optimizer | None


# The started run of an optimizer on a world and the optimizer.
def start_optimizer(
    client: httpx.Client,
    no_decisions_run_id: str,
    agent: str,
    time_limit: float,
    world: World,
) -> tuple[dict[str, Any], Optimizer]:
    if agent == "reference":
        return start_reference(
            client, world.scenario_id, world.seed, no_decisions_run_id, time_limit
        )
    if agent in INFORMED_FACTORS:
        shown = benchmark.create_shown_description(
            client, world.manifest_id, world.seed, world.scenario_content
        )
        run = benchmark.start_run(client, world.scenario_id, world.seed)
        check = partial(benchmark.create_check, client, run["id"])
        factor = INFORMED_FACTORS[agent]
        return run, informed_optimizer(check, factor, shown, time_limit)
    run = benchmark.start_run(client, world.scenario_id, world.seed)
    check = partial(benchmark.create_check, client, run["id"])
    return run, LIMITED_CONSTRUCTORS[agent](check, time_limit)


def play_agent(
    client: httpx.Client,
    no_decisions_run_id: str,
    agent: str,
    time_limit: float,
    world: World,
) -> AgentPlay:
    optimizer = None
    if agent == "no_decisions":
        started = time.monotonic()
        run, result = play_no_decisions(client, world.scenario_id, world.seed)
    else:
        run, optimizer = start_optimizer(
            client, no_decisions_run_id, agent, time_limit, world
        )
        started = time.monotonic()
        result = benchmark.play_run(client, run, optimizer)
    seconds = time.monotonic() - started
    solves = [] if optimizer is None else optimizer.solves
    play = Play(
        run_id=run["id"],
        result=result,
        periods=benchmark.read_periods(client, run["id"]),
        solves_at_time_limit=sum(solve.stopped_at_time_limit for solve in solves),
    )
    return AgentPlay(
        agent=agent,
        description=run["description"],
        play=play,
        seconds=seconds,
        optimizer=optimizer,
    )


# The agents of a world played in order on new runs of it.
def play_agents(
    client: httpx.Client, time_limit: float, world: World
) -> list[AgentPlay]:
    plays: list[AgentPlay] = []
    for agent in world.agents:
        no_decisions_run_id = plays[0].play.run_id if plays else ""
        try:
            plays.append(
                play_agent(client, no_decisions_run_id, agent, time_limit, world)
            )
        except Exception as error:
            raise WorldError(f"{agent}: {type(error).__name__}: {error}") from error
    return plays


def indexed_run(
    world: World,
    agent_play: AgentPlay,
    number: int,
    violations: list[str],
    settings: str,
    code: str,
    checks: str,
    ended: str,
) -> PlayedRun:
    optimizer = agent_play.optimizer
    solves = [] if optimizer is None else optimizer.solves
    gaps = [solve.gap for solve in solves if solve.solution_found]
    result = agent_play.play.result
    return PlayedRun(
        scenario=world.scenario,
        scenario_id=world.scenario_id,
        seed=world.seed,
        agent=agent_play.agent,
        play=number,
        run_id=agent_play.play.run_id,
        profit=Decimal(result["profit"]),
        seconds=agent_play.seconds,
        solves=len(solves),
        solves_at_time_limit=agent_play.play.solves_at_time_limit,
        solves_without_solution=sum(not solve.solution_found for solve in solves),
        dropped=None if optimizer is None else len(optimizer.dropped),
        fitted=None if optimizer is None else len(optimizer.fitted),
        relaxed_program_value=(
            optimizer.relaxed_program_value
            if optimizer is not None and agent_play.agent == "reference"
            else None
        ),
        linear=None if optimizer is None else not solves,
        largest_gap=max(gaps, default=None),
        violations=tuple(violations),
        settings=settings,
        version=version("factory-simulator"),
        code=code,
        solver_environment=build_solver_environment(),
        checks=checks,
        time=ended,
        measures={path: measure_value(result, path) for path in MEASURE_PATHS},
    )


# The play of the agents of a world, twice with `replay`, with every run checked: its
# rows, with the digests of the code and of the checks, or none and the violation of the
# exception that ended it.
def play_world(
    client: httpx.Client, time_limit: float, code: str, checks: str, world: World
) -> tuple[list[PlayedRun], list[str]]:
    try:
        plays = [play_agents(client, time_limit, world)]
        if world.replay:
            plays.append(play_agents(client, time_limit, world))
    except WorldError as error:
        return [], [str(error)]
    ended = datetime.now().isoformat(timespec="seconds")
    runs: list[PlayedRun] = []
    for number, agent_plays in enumerate(plays, start=1):
        for position, agent_play in enumerate(agent_plays):
            first = plays[0][position].play if number == 2 else None
            violations = violations_of_play(
                agent_play.agent, agent_play.description, agent_play.play, first
            )
            runs.append(
                indexed_run(
                    world,
                    agent_play,
                    number,
                    violations,
                    settings_of(time_limit),
                    code,
                    checks,
                    ended,
                )
            )
    return runs, []


# The play of a world in a process of the pool, with a client of its own.
def play_world_at(
    url: str, time_limit: float, code: str, checks: str, world: World
) -> tuple[list[PlayedRun], list[str]]:
    with httpx.Client(base_url=url, timeout=None) as client:
        return play_world(client, time_limit, code, checks, world)


# The play of the worlds over the server of the URL; see `play_worlds_in_pool`.
def play_worlds(
    url: str,
    worlds: list[World],
    workers: int,
    time_limit: float,
    code: str,
    checks: str,
    index: Path,
) -> list[str]:
    play = partial(play_world_at, url, time_limit, code, checks)
    return play_worlds_in_pool(play, worlds, workers, index)


# The play of a world in a process of the pool; any exception it raises becomes the
# violation `<type>: <message>`, so no exception has to pass back to the session.
def play_world_in_worker(
    play: WorldPlay, world: World
) -> tuple[list[PlayedRun], list[str]]:
    try:
        return play(world)
    except Exception as error:
        return [], [f"{type(error).__name__}: {error}"]


# The play of the worlds in a pool of processes: each complete world goes into the index
# as it ends, its rows with the digests of the code and of the checks, with a printed
# line, and the result is the violations of the worlds that did not complete. A world
# that raises in its worker is one of them and the others go on; a pool whose process
# ends abruptly fails every world it has not completed. When the session itself raises,
# as when it cannot write the index, the pool cancels the worlds that have not started
# and the exception passes on.
def play_worlds_in_pool(
    play: WorldPlay, worlds: list[World], workers: int, index: Path
) -> list[str]:
    violations: list[str] = []
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        futures = {
            pool.submit(play_world_in_worker, play, world): world for world in worlds
        }
        try:
            for future in as_completed(futures):
                world = futures[future]
                try:
                    runs, failures = future.result()
                except Exception as error:
                    runs, failures = [], [f"{type(error).__name__}: {error}"]
                if runs:
                    append_to_index(index, runs)
                violations += [
                    f"{world.scenario} seed {world.seed}: {failure}"
                    for failure in failures
                ]
                seconds = sum(run.seconds for run in runs)
                count = sum(len(run.violations) for run in runs) + len(failures)
                print(
                    f"{world.scenario} seed {world.seed}: {len(runs)} runs, "
                    f"{seconds:.1f} s, {count} violations",
                    flush=True,
                )
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return violations


# The description and the play of a stored run, read back over HTTP.
def read_stored_play(client: httpx.Client, run: PlayedRun) -> tuple[JsonObject, Play]:
    description = benchmark.read(client, f"/runs/{run.run_id}")["description"]
    play = Play(
        run_id=run.run_id,
        result=benchmark.read(client, f"/runs/{run.run_id}/result"),
        periods=benchmark.read_periods(client, run.run_id),
        solves_at_time_limit=run.solves_at_time_limit,
    )
    return description, play


# The runs, each world that holds a run of other checks checked again as a whole from
# its stored plays: every run of it gets the violations of the current checks and their
# digest. The rows of one world share the scenario, the seed and the identity. A world
# with a run the server cannot read keeps its rows, and gives a message for each such
# run.
def rechecked_runs(
    client: httpx.Client,
    runs: list[PlayedRun],
    checks: str,
    violations_of: PlayChecks,
) -> tuple[list[PlayedRun], list[str]]:
    worlds: dict[tuple[str, int, RunIdentity], list[int]] = {}
    for position, run in enumerate(runs):
        key = (run.scenario_id, run.seed, identity_of(run))
        worlds.setdefault(key, []).append(position)
    checked = list(runs)
    missing: list[str] = []
    for positions in worlds.values():
        if all(runs[position].checks == checks for position in positions):
            continue
        stored: dict[int, tuple[JsonObject, Play]] = {}
        unread: list[str] = []
        for position in positions:
            run = runs[position]
            try:
                stored[position] = read_stored_play(client, run)
            except RuntimeError as error:
                unread.append(
                    f"{run.scenario} seed {run.seed} {run.agent} {run.run_id}: the "
                    "stored run cannot be read, so the current checks did not run: "
                    f"{error}"
                )
        if unread:
            missing += unread
            continue
        firsts = {
            runs[position].agent: stored[position][1]
            for position in positions
            if runs[position].play == 1
        }
        for position in positions:
            run = runs[position]
            description, play = stored[position]
            first = firsts.get(run.agent) if run.play == 2 else None
            violations = violations_of(run.agent, description, play, first)
            checked[position] = replace(
                run, violations=tuple(violations), checks=checks
            )
    return checked, missing


# The second check of the runs of the index under an identity whose checks are not the
# current ones: the runs are written back, a line prints how many changed, and the
# result is the messages of the runs the server cannot read.
def recheck_index(
    client: httpx.Client,
    index: Path,
    identity: RunIdentity,
    checks: str,
    violations_of: PlayChecks,
) -> list[str]:
    runs = read_index(index)
    positions = [
        position for position, run in enumerate(runs) if identity_of(run) == identity
    ]
    checked, missing = rechecked_runs(
        client, [runs[position] for position in positions], checks, violations_of
    )
    changed = list(runs)
    for position, run in zip(positions, checked, strict=True):
        changed[position] = run
    count = sum(before != after for before, after in zip(runs, changed, strict=True))
    if count:
        write_index(index, changed)
    print(f"runs checked again: {count}", flush=True)
    return missing
