"""The service of scenarios: create, list and read scenarios of a manifest.

Examples:
    >>> from factory_simulator.api.record import database
    >>> database_engine = database.create_database_engine("duckdb:///:memory:")
    >>> database.prepare(database_engine, "0.1.0")
    >>> session = Session(database_engine, expire_on_commit=False)
    >>> list_scenarios(session, "m-1")
    Traceback (most recent call last):
    ...
    factory_simulator.api.core.errors.NotFoundError: manifest_id: unknown manifest m-1
"""

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.errors import NotFoundError
from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.api.record.repositories import scenarios
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.manifests import (
    content_id,
    stored_manifest,
    summary,
)
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.api.services.readers.scenario import to_scenario


def create_scenario(
    session: Session, manifest_id: str, body: bytes
) -> tuple[int, dict[str, object]]:
    """Create a scenario of a manifest, or find the same one already stored.

    Args:
        session (Session): The session of the request.
        manifest_id (str): The identifier of the manifest.
        body (bytes): The raw body.

    Returns:
        tuple[int, dict[str, object]]: 201 and the new scenario, or 200 and the
            stored one.

    Raises:
        NotFoundError: If the manifest does not exist.
        InputError: If the body is not a valid scenario.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> body = b'{"horizon": 3}'
        >>> status, _ = create_scenario(session, manifest["id"], body)
        >>> status
        201
    """
    manifest = stored_manifest(session, manifest_id)
    model = validate(ScenarioCreate, read_json_bytes(body))
    factory = read_factory(manifest.content)
    engine.check_scenario(to_scenario(model), factory)
    content = model.model_dump(mode="python")
    scenario = Scenario(
        id=content_id({"manifest_id": manifest_id, "scenario": content}),
        manifest_id=manifest_id,
        content=content,
    )
    created = scenarios.add_scenario(session, scenario)
    return (201 if created else 200), read_scenario(session, scenario.id)


def stored_scenario(session: Session, scenario_id: str) -> Scenario:
    """Give a stored scenario, or refuse an unknown one.

    Args:
        session (Session): The session of the request.
        scenario_id (str): The identifier of the scenario.

    Returns:
        Scenario: The scenario.

    Raises:
        NotFoundError: If the scenario does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> body = b'{"horizon": 3}'
        >>> _, scenario = create_scenario(session, manifest["id"], body)
        >>> stored_scenario(session, scenario["id"]).manifest_id == manifest["id"]
        True
    """
    scenario = scenarios.find_scenario(session, scenario_id)
    if scenario is None:
        raise NotFoundError(f"scenario_id: unknown scenario {scenario_id}")
    return scenario


def read_scenario(session: Session, scenario_id: str) -> dict[str, object]:
    """Read a stored scenario.

    Args:
        session (Session): The session of the request.
        scenario_id (str): The identifier of the scenario.

    Returns:
        dict[str, object]: `{"id", "content"}`.

    Raises:
        NotFoundError: If the scenario does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> body = b'{"horizon": 3}'
        >>> _, scenario = create_scenario(session, manifest["id"], body)
        >>> read_scenario(session, scenario["id"])["content"]["horizon"]
        3
    """
    scenario = stored_scenario(session, scenario_id)
    return {"id": scenario.id, "content": scenario.content}


def list_scenarios(session: Session, manifest_id: str) -> object:
    """List the scenarios of a manifest by identifier.

    Args:
        session (Session): The session of the request.
        manifest_id (str): The identifier of the manifest.

    Returns:
        object: `{"scenarios": [{"id", "name", "description"}, ...]}`.

    Raises:
        NotFoundError: If the manifest does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> _ = create_scenario(session, manifest["id"], b'{"horizon": 3}')
        >>> len(list_scenarios(session, manifest["id"])["scenarios"])
        1
    """
    stored_manifest(session, manifest_id)
    found = scenarios.list_scenarios(session, manifest_id)
    return {"scenarios": [summary(*row) for row in found]}
