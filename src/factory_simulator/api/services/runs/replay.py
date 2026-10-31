"""The replay of a run: its periods played again from the record, to rebuild or fork it.

Examples:
    >>> running_versions(Server(version="0.1.0"))["package_version"]
    '0.1.0'
"""

import platform
import sys
from collections.abc import Mapping
from typing import cast

import duckdb
import numpy
import pydantic
from sqlalchemy import JSON
from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.errors import ConflictError
from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import validate
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.run import Period, Run
from factory_simulator.api.record.repositories import runs
from factory_simulator.api.schemas.run import DecisionsCreate
from factory_simulator.api.services.readers.decisions import to_decisions
from factory_simulator.api.services.runs.memory import RunMemory, Server
from factory_simulator.api.services.runs.rows import (
    PERIOD_TABLES,
    period_rows,
    read_period_rows,
)
from factory_simulator.api.services.runs.stored import read_inputs
from factory_simulator.api.services.writers.world import world_json

# The versions a rebuilt run must share with the server, and how many leading
# dot-separated parts of each are compared; None compares the whole text.
COMPARED_VERSIONS: dict[str, int | None] = {
    "package_version": None,
    "numpy_version": None,
    "python_version": 2,
}


def rebuild_run(server: Server, session: Session, run: Run) -> RunMemory:
    """Rebuild the state of a running run from its record, writing nothing.

    Args:
        server (Server): The server.
        session (Session): The session of the request.
        run (Run): The unfinished run.

    Returns:
        RunMemory: The world and the state of the run at its stored period, and
            the number of its interactions.

    Raises:
        ConflictError: If the version, the world or a period differs, at the first
            one that differs.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> old = Run(
        ...     id="r-1",
        ...     period=2,
        ...     package_version="0.0.9",
        ...     numpy_version="2.0.0",
        ...     python_version="3.14.0",
        ... )
        >>> server = Server(version="0.1.0")
        >>> rebuild_run(server, session, old)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.ConflictError:
        runs.package_version: recorded 0.0.9, running 0.1.0
    """
    interaction_count = runs.count_interactions(session, run.id)
    world, _, state = replay_run(server, session, run, run.period - 1)
    return RunMemory(world=world, state=state, interaction_count=interaction_count)


def replay_run(
    server: Server, session: Session, run: Run, last: int
) -> tuple[engine.World, list[tuple[engine.State, DecisionsCreate]], engine.State]:
    """Replay the first periods of a run from its record, writing nothing.

    It compares the versions and reads every stored row it needs, then ends the
    transaction, so the replay holds no connection. It draws the world again and
    compares it with the record, then checks each stored period, replays its
    submission and compares the rows the period would write with the stored ones.
    The run is expired once the transaction ends.

    Args:
        server (Server): The server.
        session (Session): The session of the request.
        run (Run): The run.
        last (int): The last period to replay, 0 for none.

    Returns:
        tuple[World, list[tuple[State, DecisionsCreate]], State]: The world, the
            closed state and submission of each replayed period, and the state of
            the next period once started.

    Raises:
        ConflictError: If the version, the world or a period differs, at the first
            one that differs. A period differs when it has no stored row or more
            than one, when its stored submission does not read as decisions, when
            the submission names another period, or when its replayed rows differ
            from the stored ones.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> old = Run(
        ...     id="r-1",
        ...     period=2,
        ...     package_version="0.0.9",
        ...     numpy_version="2.0.0",
        ...     python_version="3.14.0",
        ... )
        >>> server = Server(version="0.1.0")
        >>> replay_run(server, session, old, 0)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.ConflictError:
        runs.package_version: recorded 0.0.9, running 0.1.0
    """
    running = running_versions(server)
    for name, parts in COMPARED_VERSIONS.items():
        recorded = cast(str, getattr(run, name))
        if recorded.split(".")[:parts] != running[name].split(".")[:parts]:
            raise ConflictError(
                f"runs.{name}: recorded {recorded}, running {running[name]}"
            )
    factory, scenario = read_inputs(run.scenario)
    run_id = run.id
    seed = int(run.seed)
    recorded_world = None if run.world is None else run.world.world
    stored = read_period_rows(session, run_id, last)
    world = engine.draw_world(factory, scenario, seed)
    if recorded_world is None or write_json(world_json(world)) != write_json(
        recorded_world
    ):
        raise ConflictError("world: does not match the record")
    state = engine.start_period(engine.build_state(world), world)
    closed_periods: list[tuple[engine.State, DecisionsCreate]] = []
    for period in range(1, last + 1):
        differs = ConflictError(
            f"periods.{period}: replayed period differs from the record"
        )
        kept_periods = stored[Period].get(period, [])
        if len(kept_periods) != 1:
            raise differs
        try:
            submission = validate(DecisionsCreate, kept_periods[0]["submission"])
        except engine.InputError:
            raise differs from None
        if submission.period != period:
            raise differs
        closed = engine.advance_period(state, world, to_decisions(submission))
        replayed = period_rows(run_id, closed, submission, world)
        for table in PERIOD_TABLES:
            written = [row_values(table, row) for row in replayed[table]]
            kept = [row_values(table, row) for row in stored[table].get(period, [])]
            if written != kept:
                raise differs
        closed_periods.append((closed, submission))
        state = engine.start_period(closed, world)
    return world, closed_periods, state


def running_versions(server: Server) -> dict[str, str]:
    """Give the versions and the platform a new run records.

    Args:
        server (Server): The server.

    Returns:
        dict[str, str]: The value of each column of versions of `runs`.

    Examples:
        >>> running_versions(Server(version="0.1.0"))["package_version"]
        '0.1.0'
    """
    return {
        "package_version": server.version,
        "numpy_version": numpy.__version__,
        "python_version": platform.python_version(),
        "pydantic_version": pydantic.VERSION,
        "duckdb_version": duckdb.__version__,
        "platform": sys.platform,
    }


def row_values(table: type[Base], values: Mapping[str, object]) -> dict[str, object]:
    """Give the values of a row to compare, JSON columns as their canonical text.

    Args:
        table (type[Base]): The mapped class of the table.
        values (Mapping[str, object]): The value of each column by its name.

    Returns:
        dict[str, object]: The value of each column by its name.

    Examples:
        >>> from factory_simulator.api.record.models.run import World
        >>> row_values(World, {"run_id": "r-1", "world": {"b": 1, "a": 2}})
        {'run_id': 'r-1', 'world': b'{"a":2,"b":1}'}
    """
    return {
        column.key: write_json(values[column.key])
        if isinstance(column.type, JSON)
        else values[column.key]
        for column in table.__table__.columns
    }
