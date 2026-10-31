"""The routes of scenarios: read a scenario.

Examples:
    >>> router.prefix
    '/scenarios'
"""

from fastapi import APIRouter, Response

from factory_simulator.api.dependencies import SessionDependency
from factory_simulator.api.routes import answer, error_responses
from factory_simulator.api.schemas.scenario import ScenarioPublic
from factory_simulator.api.services import scenarios

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get(
    "/{scenario_id}", response_model=ScenarioPublic, responses=error_responses(404)
)
def read_scenario(scenario_id: str, session: SessionDependency) -> Response:
    """Read a stored scenario.

    200 and the scenario with its content; 404 if the scenario does not exist; 503 if no
    connection of the database is free within 30 s.
    \f

    Args:
        scenario_id (str): The identifier of the scenario.
        session (Session): The session of the request.

    Returns:
        Response: The scenario with its content.

    Raises:
        NotFoundError: If the scenario does not exist.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_scenario"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     client.get(f"/scenarios/{scenario['id']}").status_code
        200
    """  # noqa: D301
    return answer(scenarios.read_scenario(session, scenario_id))
