"""The fork of a run: a new run from a period of a finished run, its past replayed.

Examples:
    >>> from factory_simulator.api.record import database
    >>> database_engine = database.create_database_engine("duckdb:///:memory:")
    >>> database.prepare(database_engine, "0.1.0")
    >>> session = Session(database_engine, expire_on_commit=False)
    >>> fork_run(Server(version="0.1.0"), session, "r-1", b'{"period": 1}')
    Traceback (most recent call last):
    ...
    factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
"""

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.record.models.run import Run, World
from factory_simulator.api.record.repositories import runs, save
from factory_simulator.api.schemas.run import ForkCreate
from factory_simulator.api.services.runs.memory import RunMemory, Server, keep_memory
from factory_simulator.api.services.runs.replay import replay_run, running_versions
from factory_simulator.api.services.runs.rows import period_rows
from factory_simulator.api.services.runs.runs import locked_run, read_run
from factory_simulator.api.services.runs.stored import (
    create_run_id,
    finished_run,
    stored_run,
)
from factory_simulator.api.services.writers.world import world_json


def fork_run(server: Server, session: Session, run_id: str, body: bytes) -> object:
    """Fork a finished run: start a new run from one of its periods, replaying the past.

    The replay of the parent holds no connection; the new run and its replayed
    periods are then written in one transaction.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        body (bytes): The raw body, `{"period"}`.

    Returns:
        object: The new run at the period, `{"id", "scenario_id", "description",
            "period", "finished"}`.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the parent is not finished, or its record does not replay.
        InputError: If the body is not valid or the period is outside the horizon.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> fork_run(Server(version="0.1.0"), session, "r-1", b'{"period": 1}')
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    parent = stored_run(session, run_id)
    with locked_run(server, session, parent):
        parent = finished_run(session, run_id)
        request = validate(ForkCreate, read_json_bytes(body))
        # A finished run stays in its last period, the horizon.
        if not 1 <= request.period <= parent.period:
            raise engine.InputError("period: is not from 1 to the horizon")
        world, closed_periods, state = replay_run(
            server, session, parent, request.period - 1
        )
        child = Run(
            id=create_run_id(),
            scenario_id=parent.scenario_id,
            seed=parent.seed,
            period=request.period,
            finished=False,
            description=parent.description,
            forked_from=parent.id,
            forked_from_period=request.period,
            **running_versions(server),
        )
        save(session, child, World(run_id=child.id, world=world_json(world)))
        session.flush()
        for closed, submission in closed_periods:
            runs.insert_rows(session, period_rows(child.id, closed, submission, world))
        session.commit()
    keep_memory(server, child.id, RunMemory(world=world, state=state))
    return read_run(server, session, child.id)
