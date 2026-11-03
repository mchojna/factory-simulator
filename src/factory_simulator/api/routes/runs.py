"""The routes of runs: start, read, submit, check, fork, export, and what a run holds.

Examples:
    >>> router.prefix
    '/runs'
"""

import tempfile
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Response

from factory_simulator.api.dependencies import (
    BodyDependency,
    ServerDependency,
    SessionDependency,
    link_resources,
)
from factory_simulator.api.routes import answer, body_schema, error_responses
from factory_simulator.api.schemas.run import (
    ChecksPublic,
    DecisionsCreate,
    ForkCreate,
    ObservationPublic,
    PeriodsPublic,
    ResultPublic,
    RunCreate,
    RunPublic,
)
from factory_simulator.api.services.runs import export, fork, periods, results, runs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post(
    "",
    status_code=201,
    response_model=RunPublic,
    responses=error_responses(404, 422),
    openapi_extra=body_schema(RunCreate),
)
def start_run(
    body: BodyDependency, server: ServerDependency, session: SessionDependency
) -> Response:
    """Start a run of a scenario with a seed.

    201 and the run in period 1; 404 if the scenario does not exist; 422 if the body
    breaks a rule; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        body (bytes): The scenario identifier and the seed as JSON.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: 201 and the run in period 1.

    Raises:
        NotFoundError: If the scenario does not exist.
        InputError: If the body is not valid.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:start_run"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     client.post("/runs", json=body).status_code
        201
    """  # noqa: D301
    run = cast(dict[str, object], runs.start_run(server, session, body))
    link_resources(session, run_id=str(run["id"]), scenario_id=str(run["scenario_id"]))
    return answer(run, 201)


@router.get("/{run_id}", response_model=RunPublic, responses=error_responses(404, 409))
def read_run(
    run_id: str, server: ServerDependency, session: SessionDependency
) -> Response:
    """Read a run: its description, period and whether it is finished.

    200 and the run; 404 if the run does not exist; 409 if the record of the run does
    not rebuild it; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: The run.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the record of the run does not rebuild it.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_run"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     client.get(f"/runs/{run['id']}").status_code
        200
    """  # noqa: D301
    return answer(runs.read_run(server, session, run_id))


@router.get(
    "/{run_id}/observation",
    response_model=ObservationPublic,
    responses=error_responses(404, 409),
)
def read_observation(
    run_id: str, server: ServerDependency, session: SessionDependency
) -> Response:
    """Read the observation of the current period.

    200 and the observation; 404 if the run does not exist; 409 if the run is finished
    or its record does not rebuild it; 503 if no connection of the database is free
    within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: The observation.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, or its record does not rebuild it.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_observation"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     client.get(f"/runs/{run['id']}/observation").status_code
        200
    """  # noqa: D301
    return answer(runs.read_observation(server, session, run_id))


@router.post(
    "/{run_id}/decisions",
    response_model=ObservationPublic | RunPublic,
    responses=error_responses(404, 409, 422),
    openapi_extra=body_schema(DecisionsCreate),
)
def submit_decisions(
    run_id: str,
    body: BodyDependency,
    server: ServerDependency,
    session: SessionDependency,
) -> Response:
    """Submit the decisions of the current period.

    200 and the observation of the next period, or the run after the last period; 404 if
    the run does not exist; 409 if the run is finished, its record does not rebuild it,
    or the body names another period; 422 if the body breaks a rule; 503 if no
    connection of the database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        body (bytes): The period and its decisions as JSON.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: The observation of the next period, or the run after the last one.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, its record does not rebuild it, or the
            submission names another period.
        InputError: If the body is not a valid submission.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:submit_decisions"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     empty = {"period": 1, "decisions": []}
        ...     client.post(f"/runs/{run['id']}/decisions", json=empty).status_code
        200
    """  # noqa: D301
    return answer(runs.submit_decisions(server, session, run_id, body))


@router.post(
    "/{run_id}/checks",
    response_model=ChecksPublic,
    responses=error_responses(404, 409, 422),
    openapi_extra=body_schema(DecisionsCreate),
)
def create_check(
    run_id: str,
    body: BodyDependency,
    server: ServerDependency,
    session: SessionDependency,
) -> Response:
    """Create a check of the decisions of the current period, the run unchanged.

    200 and the outcomes the decisions would have, in execution order; 404 if the run
    does not exist; 409 if the run is finished, its record does not rebuild it, or the
    body names another period; 422 if the body breaks a rule; 503 if no connection of
    the database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        body (bytes): The period and its decisions as JSON.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: The outcomes the decisions would have, in execution order.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is finished, its record does not rebuild it, or the
            check names another period.
        InputError: If the body is not a valid submission.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:create_check"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     empty = {"period": 1, "decisions": []}
        ...     client.post(f"/runs/{run['id']}/checks", json=empty).json()
        {'outcomes': []}
    """  # noqa: D301
    return answer(runs.create_check(server, session, run_id, body))


@router.post(
    "/{run_id}/forks",
    status_code=201,
    response_model=RunPublic,
    responses=error_responses(404, 409, 422),
    openapi_extra=body_schema(ForkCreate),
)
def fork_run(
    run_id: str,
    body: BodyDependency,
    server: ServerDependency,
    session: SessionDependency,
) -> Response:
    """Fork a finished run: start a new run from one of its periods, replaying the past.

    201 and the new run at the period; 404 if the run does not exist; 409 if the run is
    not finished or its record does not replay; 422 if the body breaks a rule or the
    period is outside the horizon; 503 if no connection of the database is free within
    30 s.
    \f

    Args:
        run_id (str): The identifier of the finished run.
        body (bytes): The period as JSON, `{"period"}`.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: 201 and the new run at the period.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished, or its record does not replay.
        InputError: If the body is not valid or the period is outside the horizon.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:fork_run"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     decisions = f"/runs/{run['id']}/decisions"
        ...     for period in (1, 2, 3):
        ...         empty = {"period": period, "decisions": []}
        ...         _ = client.post(decisions, json=empty)
        ...     start = {"period": 2}
        ...     client.post(f"/runs/{run['id']}/forks", json=start).status_code
        201
    """  # noqa: D301
    created = cast(dict[str, object], fork.fork_run(server, session, run_id, body))
    link_resources(
        session, run_id=str(created["id"]), scenario_id=str(created["scenario_id"])
    )
    return answer(created, 201)


@router.get(
    "/{run_id}/periods",
    response_model=PeriodsPublic,
    responses=error_responses(404, 409),
)
def read_periods(
    run_id: str, server: ServerDependency, session: SessionDependency
) -> Response:
    """Read every closed period of a run.

    200 and each closed period with its six steps and ledger rows; 404 if the run does
    not exist; 409 if the record of a running run does not rebuild it; 503 if no
    connection of the database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        server (Server): The server, changed in place.
        session (Session): The session of the request.

    Returns:
        Response: Each closed period with its six steps and ledger rows.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is running and its record does not rebuild it.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_periods"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     client.get(f"/runs/{run['id']}/periods").json()
        {'periods': []}
    """  # noqa: D301
    return answer(periods.read_periods(server, session, run_id))


@router.get(
    "/{run_id}/result",
    response_model=ResultPublic,
    responses=error_responses(404, 409),
)
def read_result(run_id: str, session: SessionDependency) -> Response:
    """Read the result of a finished run.

    200 and the seed, profit, cash and every term of profit; 404 if the run does not
    exist; 409 if the run is not finished; 503 if no connection of the database is free
    within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        session (Session): The session of the request.

    Returns:
        Response: The seed, profit, cash and every term of profit.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_result"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     decisions = f"/runs/{run['id']}/decisions"
        ...     for period in (1, 2, 3):
        ...         empty = {"period": period, "decisions": []}
        ...         _ = client.post(decisions, json=empty)
        ...     client.get(f"/runs/{run['id']}/result").status_code
        200
    """  # noqa: D301
    return answer(results.read_result(session, run_id))


@router.get("/{run_id}/world", responses=error_responses(404, 409))
def read_world(run_id: str, session: SessionDependency) -> Response:
    """Read the world of a finished run.

    200 and every value drawn from the seed; 404 if the run does not exist; 409 if the
    run is not finished; 503 if no connection of the database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        session (Session): The session of the request.

    Returns:
        Response: Every value drawn from the seed.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:read_world"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     decisions = f"/runs/{run['id']}/decisions"
        ...     for period in (1, 2, 3):
        ...         empty = {"period": period, "decisions": []}
        ...         _ = client.post(decisions, json=empty)
        ...     client.get(f"/runs/{run['id']}/world").status_code
        200
    """  # noqa: D301
    return answer(runs.read_world(session, run_id))


@router.get(
    "/{run_id}/export",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {}}},
        **error_responses(404, 409),
    },
)
def export_run(run_id: str, session: SessionDependency) -> Response:
    """Export a finished run as one ZIP file of its tables, operations and inputs.

    200 and one ZIP file of the tables, operations and inputs of the run; 404 if the
    run does not exist; 409 if the run is not finished; 503 if no connection of the
    database is free within 30 s.
    \f

    Args:
        run_id (str): The identifier of the run.
        session (Session): The session of the request.

    Returns:
        Response: The file `<run id>.zip`, read from a temporary folder that is
            removed before it is sent.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> from factory_simulator.api.core.config import Settings
        >>> from factory_simulator.api.main import create_app
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> url = "duckdb:///:memory:export_run"
        >>> app = create_app(Settings(database_url=url, load_examples=False))
        >>> manifest = (EXAMPLES / "manifest.json").read_bytes()
        >>> with TestClient(app, base_url="http://test/api/v1") as client:
        ...     factory = client.post("/manifests", content=manifest).json()
        ...     path = f"/manifests/{factory['id']}/scenarios"
        ...     scenario = client.post(path, json={"horizon": 3}).json()
        ...     body = {"scenario_id": scenario["id"], "seed": 1}
        ...     run = client.post("/runs", json=body).json()
        ...     decisions = f"/runs/{run['id']}/decisions"
        ...     for period in (1, 2, 3):
        ...         empty = {"period": period, "decisions": []}
        ...         _ = client.post(decisions, json=empty)
        ...     client.get(f"/runs/{run['id']}/export").status_code
        200
    """  # noqa: D301
    with tempfile.TemporaryDirectory() as folder:
        path = export.export_run(session, run_id, Path(folder))
        content = path.read_bytes()
    return Response(
        content,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{path.name}"'},
    )
