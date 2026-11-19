"""The life of a run: start it, read it, submit to it and check it.

Examples:
    >>> run_json(Run(id="r-1", finished=False), 1)["finished"]
    False
"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from typing import Literal, cast

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.errors import ConflictError
from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.record.models.run import Run, World
from factory_simulator.api.record.repositories import runs, save
from factory_simulator.api.schemas.run import DecisionsCreate, RunCreate
from factory_simulator.api.services.readers.decisions import to_decisions, with_defaults
from factory_simulator.api.services.runs.memory import (
    RunMemory,
    Server,
    forget_memory,
    hold_lock,
    keep_memory,
    memory_of,
)
from factory_simulator.api.services.runs.replay import rebuild_run, running_versions
from factory_simulator.api.services.runs.rows import write_period
from factory_simulator.api.services.runs.stored import (
    create_run_id,
    finished_run,
    read_inputs,
    stored_run,
)
from factory_simulator.api.services.scenarios import stored_scenario
from factory_simulator.api.services.writers.description import description_json
from factory_simulator.api.services.writers.observation import observation_json
from factory_simulator.api.services.writers.values import plain
from factory_simulator.api.services.writers.world import world_json


def start_run(server: Server, session: Session, body: bytes) -> object:
    """Start a run of a scenario with a seed and start period 1.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        body (bytes): The raw body, `{"scenario_id", "seed"}`.

    Returns:
        object: The run, `{"id", "scenario_id", "description", "period", "finished"}`.

    Raises:
        NotFoundError: If the scenario does not exist.
        InputError: If the body is not valid.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> body = b'{"scenario_id": "s-1", "seed": 7}'
        >>> server = Server(version="0.1.0")
        >>> start_run(server, session, body)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError:
        scenario_id: unknown scenario s-1
    """
    request = validate(RunCreate, read_json_bytes(body))
    stored = stored_scenario(session, request.scenario_id)
    factory, scenario = read_inputs(stored)
    written_groups = cast(dict[str, object], stored.manifest.content).get("groups", {})
    written_random = cast(dict[str, object], stored.content).get(
        "random_disruptions", []
    )
    session.rollback()
    world = engine.draw_world(factory, scenario, request.seed)
    state = engine.start_period(engine.build_state(world), world)
    run = Run(
        id=create_run_id(),
        scenario_id=request.scenario_id,
        seed=str(request.seed),
        period=state.period,
        finished=False,
        description=description_json(
            engine.build_description(world),
            written_groups,
            written_random,
            scenario.hidden,
        ),
        **running_versions(server),
    )
    save(session, run, World(run_id=run.id, world=world_json(world)))
    session.commit()
    keep_memory(server, run.id, RunMemory(world=world, state=state))
    return read_run(server, session, run.id)


def read_run(server: Server, session: Session, run_id: str) -> object:
    """Read a run: its description, period and whether it is finished.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        object: `{"id", "scenario_id", "description", "period", "finished"}`.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If a running run is not in memory and its record does not
            rebuild it.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_run(Server(version="0.1.0"), session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = stored_run(session, run_id)
    if run.finished:
        return run_json(run, run.period)
    memory = memory_of(server, run_id)
    if memory is None:
        with locked_run(server, session, run):
            if run.finished:
                return run_json(run, run.period)
            memory = running_memory(server, session, run)
    return run_json(run, memory.state.period)


@contextmanager
def locked_run(server: Server, session: Session, run: Run) -> Generator[None]:
    """Hold the lock of a run, with the run read again once the lock is taken.

    The rollback ends the transaction begun before the lock, which gives the
    connection back while the request waits; the refresh then reads what another
    request committed meanwhile, and the commit ends that read, so the block holds no
    connection until it reads or writes again.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run (Run): The stored run, read before the lock.

    Yields:
        None: Nothing; the lock is held until the block ends.

    Examples:
        >>> from unittest.mock import Mock
        >>> session = Mock()
        >>> with locked_run(Server(version="0.1.0"), session, run := Run(id="r-1")):
        ...     session.refresh.assert_called_once_with(run)
        ...     session.commit.assert_called_once_with()
        >>> session.rollback.assert_called_once_with()
    """
    # The rollback expires the run, so its identifier is read before it.
    run_id = run.id
    session.rollback()
    with hold_lock(server, run_id):
        session.refresh(run)
        session.commit()
        yield


def run_json(run: Run, period: int) -> object:
    """Write the answer of a run at a period.

    Args:
        run (Run): The stored run.
        period (int): The period to report.

    Returns:
        object: `{"id", "scenario_id", "description", "period", "finished"}`.

    Examples:
        >>> run = Run(id="run-1", scenario_id="s-1", description={}, finished=True)
        >>> run_json(run, 52)["period"]
        52
    """
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "description": run.description,
        "period": period,
        "finished": run.finished,
    }


def running_memory(server: Server, session: Session, run: Run) -> RunMemory:
    """Give the memory of a running run, rebuilding it when the server has none.

    The caller holds the lock of the run and has read the run after taking it.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run (Run): The stored run.

    Returns:
        RunMemory: The world and state of the run.

    Raises:
        ConflictError: If the run is finished, or its record does not rebuild it.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> finished = Run(id="r-1", finished=True)
        >>> running_memory(Server(version="0.1.0"), session, finished)
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.ConflictError: run: the run is finished
    """
    if run.finished:
        raise ConflictError("run: the run is finished")
    memory = memory_of(server, run.id)
    if memory is None:
        memory = rebuild_run(server, session, run)
        keep_memory(server, run.id, memory)
    return memory


def read_running_memory(server: Server, session: Session, run_id: str) -> RunMemory:
    """Read the memory of a running run for a reading route.

    A kept memory and a finished run are read without the lock; a missing memory is
    rebuilt under it.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        RunMemory: The world and state of the run.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, or its record does not rebuild it.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_running_memory(Server(version="0.1.0"), session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    memory = memory_of(server, run_id)
    if memory is not None:
        return memory
    run = stored_run(session, run_id)
    if run.finished:
        raise ConflictError("run: the run is finished")
    with locked_run(server, session, run):
        return running_memory(server, session, run)


def read_observation(server: Server, session: Session, run_id: str) -> object:
    """Read the observation of the current period of a running run.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        object: The observation.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, or its record does not rebuild it.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_observation(Server(version="0.1.0"), session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    memory = read_running_memory(server, session, run_id)
    return observation_json(memory.state.observation, memory.world.scenario.hidden)


def submit_decisions(
    server: Server, session: Session, run_id: str, body: bytes
) -> object:
    """Submit the decisions of the period: execute them, close it, start the next one.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        body (bytes): The raw body, `{"period", "decisions"}`.

    Returns:
        object: The observation of the next period, or the run after the last one.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, its record does not rebuild it, or the
            submission names another period.
        InputError: If the body breaks the model of a submission.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> body = b'{"period": 1, "decisions": []}'
        >>> submit_decisions(Server(version="0.1.0"), session, "r-1", body)
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = stored_run(session, run_id)
    with locked_run(server, session, run):
        memory = running_memory(server, session, run)
        submission = read_submission(server, session, run_id, memory, body, "refusal")
        closed = engine.advance_period(
            memory.state, memory.world, to_decisions(submission)
        )
        following = None
        if not closed.finished:
            following = engine.start_period(closed, memory.world)
        write_period(session, run, closed, submission, memory.world)
        if following is None:
            forget_memory(server, run_id)
        else:
            keep_memory(server, run_id, replace(memory, state=following))
    if following is None:
        return run_json(run, run.period)
    return observation_json(following.observation, memory.world.scenario.hidden)


def create_check(server: Server, session: Session, run_id: str, body: bytes) -> object:
    """Create a check of the decisions of the period, as `execute_decisions` runs them.

    The check is kept in interactions; the run and the rows of its periods stay as
    they were. The recorder of operations keeps the request and its response.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        body (bytes): The raw body, `{"period", "decisions"}`.

    Returns:
        object: `{"outcomes": [...]}`, in execution order.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, its record does not rebuild it, or the
            check names another period.
        InputError: If the body breaks the model of a submission.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> body = b'{"period": 1, "decisions": []}'
        >>> create_check(Server(version="0.1.0"), session, "r-1", body)
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = stored_run(session, run_id)
    with locked_run(server, session, run):
        memory = running_memory(server, session, run)
        submission = read_submission(server, session, run_id, memory, body, "check")
        checked = engine.build_outcomes(
            memory.state, memory.world, to_decisions(submission)
        )
        outcomes = [plain(outcome) for outcome in checked]
        add_interaction(server, session, run_id, memory, "check", submission, outcomes)
    return {"outcomes": outcomes}


def add_interaction(
    server: Server,
    session: Session,
    run_id: str,
    memory: RunMemory,
    kind: Literal["check", "refusal"],
    submission: object,
    outcomes: object = None,
    refusal: str | None = None,
) -> None:
    """Add a check or a refused submission as the next interaction of a running run.

    The caller holds the lock of the run, so the count of its interactions in memory
    gives the next position.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        memory (RunMemory): The world, state and count of interactions of the run.
        kind (Literal["check", "refusal"]): A check, or a refused submission.
        submission (object): The submission, validated or as received.
        outcomes (object, optional): The outcomes of a check; None when not given,
            as for a refusal.
        refusal (str | None, optional): Why the submission was refused; None when
            not given, as for a check.

    Examples:
        >>> from decimal import Decimal
        >>> from unittest.mock import Mock
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> state = engine.start_period(engine.build_state(world), world)
        >>> memory = RunMemory(world=world, state=state, interaction_count=2)
        >>> server = Server(version="0.1.0")
        >>> add_interaction(server, Mock(), "r-1", memory, "refusal", "{", None, "x")
        >>> server.memories["r-1"].interaction_count
        3
    """
    position = memory.interaction_count + 1
    runs.add_interaction(
        session,
        run_id,
        position,
        memory.state.period,
        kind,
        submission,
        outcomes,
        refusal,
    )
    keep_memory(server, run_id, replace(memory, interaction_count=position))


def read_submission(
    server: Server,
    session: Session,
    run_id: str,
    memory: RunMemory,
    body: bytes,
    kind: Literal["check", "refusal"],
) -> DecisionsCreate:
    """Read and validate a submission of the current period, keeping a refusal.

    Args:
        server (Server): The server, changed in place by a refusal.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        memory (RunMemory): The world and state of the run.
        body (bytes): The raw body, `{"period", "decisions"}`.
        kind (Literal["check", "refusal"]): The kind of interaction a refusal is
            kept as: `refusal` for a submission, `check` for a check.

    Returns:
        DecisionsCreate: The submission with its defaults filled in.

    Raises:
        ConflictError: If the submission names another period.
        InputError: If the body breaks the model of a submission.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> state = engine.start_period(engine.build_state(world), world)
        >>> body = b'{"period": 1, "decisions": []}'
        >>> memory = RunMemory(world=world, state=state)
        >>> server = Server(version="0.1.0")
        >>> submission = read_submission(server, session, "r-1", memory, body, "check")
        >>> submission.period
        1
    """
    period = memory.state.period
    try:
        received: object = read_json_bytes(body)
    except engine.InputError as error:
        add_interaction(
            server, session, run_id, memory, kind, received_text(body), None, str(error)
        )
        raise
    try:
        submission = with_defaults(
            validate(DecisionsCreate, received), memory.world.factory
        )
        if submission.period != period:
            raise ConflictError(
                f"period: is {submission.period}, the run is in period {period}"
            )
        return submission
    except (engine.InputError, ConflictError) as error:
        add_interaction(
            server, session, run_id, memory, kind, received_text(body), None, str(error)
        )
        raise


def received_text(body: bytes) -> str:
    r"""Give a refused body as text: its text, or the repr of its bytes.

    Args:
        body (bytes): The raw body.

    Returns:
        str: The text of the body.

    Examples:
        >>> received_text(b"{not json")
        '{not json'
        >>> received_text(b"\xff")
        "b'\\xff'"
    """
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return repr(body)


def read_world(session: Session, run_id: str) -> object:
    """Read the world of a finished run.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        object: The world in the shape of the record.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_world(session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    return cast(World, finished_run(session, run_id).world).world
