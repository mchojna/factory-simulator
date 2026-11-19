"""The routes of manifests: create, generate, list and read them, and their scenarios.

Examples:
    >>> router.prefix
    '/manifests'
"""

from fastapi import APIRouter, Response

from factory_simulator.api.dependencies import (
    BodyDependency,
    SessionDependency,
    link_resources,
)
from factory_simulator.api.routes import answer, body_schema, error_responses
from factory_simulator.api.schemas.manifest import (
    ManifestCreate,
    ManifestGenerate,
    ManifestPublic,
    ManifestsPublic,
)
from factory_simulator.api.schemas.scenario import (
    ScenarioCreate,
    ScenarioPublic,
    ScenariosPublic,
)
from factory_simulator.api.services import manifests, scenarios

router = APIRouter(prefix="/manifests", tags=["manifests"])


@router.post(
    "",
    status_code=201,
    response_model=ManifestPublic,
    responses={
        200: {"model": ManifestPublic, "description": "The stored manifest"},
        **error_responses(422),
    },
    openapi_extra=body_schema(ManifestCreate),
)
def create_manifest(body: BodyDependency, session: SessionDependency) -> Response:
    """Create a manifest, or answer the stored one with the same content.

    201 and the new manifest, or 200 and the stored one with the same content; 422 if
    the body breaks a rule; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        body (bytes): The manifest as JSON.
        session (Session): The session of the request.

    Returns:
        Response: 201 and the new manifest, or 200 and the stored one.

    Raises:
        InputError: If the body is not a valid manifest.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:create_manifest"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     first = client.post("/manifests", content=manifest)
        ...     second = client.post("/manifests", content=manifest)
        >>> first.status_code, second.status_code
        (201, 200)
    """  # noqa: D301
    status, manifest = manifests.create_manifest(session, body)
    link_resources(session, manifest_id=str(manifest["id"]))
    return answer(manifest, status)


@router.post(
    "/generated",
    status_code=201,
    response_model=ManifestPublic,
    responses={
        200: {"model": ManifestPublic, "description": "The stored manifest"},
        **error_responses(422),
    },
    openapi_extra=body_schema(ManifestGenerate),
)
def generate_manifest(body: BodyDependency, session: SessionDependency) -> Response:
    """Generate a manifest from counts and a seed, or answer the stored one.

    201 and the new manifest, or 200 and the stored one with the same content; 422 if a
    count, the seed or the economy breaks a rule; 503 if no connection of the database
    is free within 30 s.
    \f

    Args:
        body (bytes): The counts, the seed and an optional economy as JSON,
            `{"counts", "seed", "economy"}`.
        session (Session): The session of the request.

    Returns:
        Response: 201 and the new manifest, or 200 and the stored one.

    Raises:
        InputError: If a count, the seed or the economy breaks a rule.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> url = "duckdb:///:memory:generate_manifest"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> counts = dict.fromkeys(["materials", "components", "products"], 1)
        >>> counts |= dict.fromkeys(["suppliers", "customers", "lines"], 1)
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     answer = client.post(
        ...         "/manifests/generated", json={"counts": counts, "seed": 0}
        ...     )
        >>> answer.status_code
        201
    """  # noqa: D301
    status, manifest = manifests.generate_manifest(session, body)
    link_resources(session, manifest_id=str(manifest["id"]))
    return answer(manifest, status)


@router.get("", response_model=ManifestsPublic, responses=error_responses())
def list_manifests(session: SessionDependency) -> Response:
    """List every stored manifest.

    200 and the identifier, name and description of each manifest; 503 if no connection
    of the database is free within 30 s.
    \f

    Args:
        session (Session): The session of the request.

    Returns:
        Response: The identifier, name and description of each manifest.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> url = "duckdb:///:memory:list_manifests"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     client.get("/manifests").json()
        {'manifests': []}
    """  # noqa: D301
    return answer(manifests.list_manifests(session))


@router.get(
    "/{manifest_id}", response_model=ManifestPublic, responses=error_responses(404)
)
def read_manifest(manifest_id: str, session: SessionDependency) -> Response:
    """Read a stored manifest.

    200 and the manifest with its content and whether it is linear; 404 if the manifest
    does not exist; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        manifest_id (str): The identifier of the manifest.
        session (Session): The session of the request.

    Returns:
        Response: The manifest with its content and whether it is linear.

    Raises:
        NotFoundError: If the manifest does not exist.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_manifest"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     client.get(f"/manifests/{factory['id']}").status_code
        200
    """  # noqa: D301
    return answer(manifests.read_manifest(session, manifest_id))


@router.post(
    "/{manifest_id}/scenarios",
    status_code=201,
    response_model=ScenarioPublic,
    responses={
        200: {"model": ScenarioPublic, "description": "The stored scenario"},
        **error_responses(404, 422),
    },
    openapi_extra=body_schema(ScenarioCreate),
)
def create_scenario(
    manifest_id: str, body: BodyDependency, session: SessionDependency
) -> Response:
    """Create a scenario of a manifest, or answer the stored one.

    201 and the new scenario, or 200 and the stored one with the same content; 404 if
    the manifest does not exist; 422 if the body breaks a rule; 503 if no connection of
    the database is free within 30 s.
    \f

    Args:
        manifest_id (str): The identifier of the manifest.
        body (bytes): The scenario as JSON.
        session (Session): The session of the request.

    Returns:
        Response: 201 and the new scenario, or 200 and the stored one.

    Raises:
        NotFoundError: If the manifest does not exist.
        InputError: If the body is not a valid scenario.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:create_scenario"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     client.post(path, json={"horizon": 3}).status_code
        201
    """  # noqa: D301
    status, scenario = scenarios.create_scenario(session, manifest_id, body)
    link_resources(session, manifest_id=manifest_id, scenario_id=str(scenario["id"]))
    return answer(scenario, status)


@router.get(
    "/{manifest_id}/scenarios",
    response_model=ScenariosPublic,
    responses=error_responses(404),
)
def list_scenarios(manifest_id: str, session: SessionDependency) -> Response:
    """List the scenarios of a manifest.

    200 and the identifier, name and description of each scenario; 404 if the manifest
    does not exist; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        manifest_id (str): The identifier of the manifest.
        session (Session): The session of the request.

    Returns:
        Response: The identifier, name and description of each scenario.

    Raises:
        NotFoundError: If the manifest does not exist.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:list_scenarios"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     client.get(f"/manifests/{factory['id']}/scenarios").json()
        {'scenarios': []}
    """  # noqa: D301
    return answer(scenarios.list_scenarios(session, manifest_id))
