"""The rows of scenarios: add, find and list.

Examples:
    >>> from factory_simulator.api.record import database
    >>> database_engine = database.create_database_engine("duckdb:///:memory:")
    >>> database.prepare(database_engine, "0.1.0")
    >>> find_scenario(Session(database_engine), "s-1") is None
    True
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.api.record.repositories import add_once


def add_scenario(session: Session, scenario: Scenario) -> bool:
    """Add a scenario unless one with its identifier is stored.

    Args:
        session (Session): The session; the function commits.
        scenario (Scenario): The new scenario.

    Returns:
        bool: True when the scenario is new.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.record.models.manifest import Manifest
        >>> session.add(Manifest(id="m-1", content={}, linear=True))
        >>> add_scenario(session, Scenario(id="s-1", manifest_id="m-1", content={}))
        True
    """
    return add_once(session, scenario, scenario.id)


def find_scenario(session: Session, scenario_id: str) -> Scenario | None:
    """Find a stored scenario.

    Args:
        session (Session): The session; its caller commits.
        scenario_id (str): The identifier of the scenario.

    Returns:
        Scenario | None: The scenario, or None when there is none.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> find_scenario(session, "s-1") is None
        True
    """
    return session.get(Scenario, scenario_id)


def list_scenarios(
    session: Session, manifest_id: str
) -> Sequence[tuple[str, str | None, str | None]]:
    """List the identifier, name and description of every scenario of a manifest.

    The database reads the name and the description out of the content, so the
    content itself is never sent.

    Args:
        session (Session): The session; its caller commits.
        manifest_id (str): The identifier of the manifest.

    Returns:
        Sequence[tuple[str, str | None, str | None]]: The identifier, name and
            description of each scenario, by identifier.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> list_scenarios(session, "m-1")
        []
    """
    statement = (
        select(
            Scenario.id,
            Scenario.content["name"].as_string(),
            Scenario.content["description"].as_string(),
        )
        .where(Scenario.manifest_id == manifest_id)
        .order_by(Scenario.id)
    )
    return session.execute(statement).all()
