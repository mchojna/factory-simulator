"""A stored run: its identifier, the run read from the record and its inputs.

Examples:
    >>> len(create_run_id())
    32
"""

import secrets

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.errors import ConflictError, NotFoundError
from factory_simulator.api.core.numbers import validate
from factory_simulator.api.record.models.run import Run
from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.api.record.repositories import runs
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.api.services.readers.scenario import to_scenario


def create_run_id() -> str:
    """Create the identifier of a new run.

    Returns:
        str: 32 lower case hexadecimal digits that cannot be guessed.

    Examples:
        >>> len(create_run_id())
        32
    """
    return secrets.token_hex(16)


def read_inputs(scenario: Scenario) -> tuple[engine.Factory, engine.Scenario]:
    """Read a stored scenario and its manifest as dataclasses of the engine.

    Args:
        scenario (Scenario): The stored scenario.

    Returns:
        tuple[Factory, Scenario]: The factory of the manifest and the scenario.

    Raises:
        InputError: If the manifest breaks a rule of the model or of the groups, or
            the scenario breaks its model.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.record.models.manifest import Manifest
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> manifest = Manifest(content=content)
        >>> _, inputs = read_inputs(Scenario(manifest=manifest, content={"horizon": 3}))
        >>> inputs.horizon
        3
    """
    factory = read_factory(scenario.manifest.content)
    return factory, to_scenario(validate(ScenarioCreate, scenario.content))


def stored_run(session: Session, run_id: str) -> Run:
    """Give a stored run, or refuse an unknown one.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        Run: The run.

    Raises:
        NotFoundError: If the run does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> stored_run(session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = runs.find_run(session, run_id)
    if run is None:
        raise NotFoundError(f"run_id: unknown run {run_id}")
    return run


def finished_run(session: Session, run_id: str) -> Run:
    """Give a stored finished run, or refuse an unknown or unfinished one.

    A finished run holds its world and its result.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        Run: The run.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> finished_run(session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = stored_run(session, run_id)
    if not run.finished:
        raise ConflictError("run: the run is not finished")
    return run
