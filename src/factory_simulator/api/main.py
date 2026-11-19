"""The FastAPI application: its lifespan, error handlers and routers.

Examples:
    >>> app.openapi_url
    '/api/v1/openapi.json'
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from importlib import metadata
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ValidationError
from pydantic.json_schema import models_json_schema
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from factory_simulator.api.core.config import Settings
from factory_simulator.api.core.errors import ConflictError, NotFoundError
from factory_simulator.api.operations import RecordedApplication
from factory_simulator.api.record import database
from factory_simulator.api.record.repositories.operations import (
    create_operation,
    finish_operation,
    recover_operations,
)
from factory_simulator.api.routes import answer, manifests, runs, scenarios
from factory_simulator.api.schemas.manifest import ManifestCreate, ManifestGenerate
from factory_simulator.api.schemas.run import DecisionsCreate, ForkCreate, RunCreate
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.examples import create_examples
from factory_simulator.api.services.runs.memory import Server
from factory_simulator.engine import InputError

PREFIX = "/api/v1"
POOL_TIMEOUT_DETAIL = database.POOL_TIMEOUT_DETAIL
DEFECT_DETAIL = "server: internal error"
BODY_MODELS: tuple[type[BaseModel], ...] = (
    ManifestCreate,
    ManifestGenerate,
    ScenarioCreate,
    RunCreate,
    DecisionsCreate,
    ForkCreate,
)


def read_settings() -> Settings:
    """Read the settings from the environment.

    Returns:
        Settings: The settings.

    Raises:
        RuntimeError: If a setting is missing or refused, with the name of its
            variable.

    Examples:
        >>> import os
        >>> from unittest import mock
        >>> url = {"FACTORY_SIMULATOR_DATABASE_URL": "duckdb:///:memory:runs"}
        >>> with mock.patch.dict(os.environ, url):
        ...     read_settings().database_url
        'duckdb:///:memory:runs'
        >>> with mock.patch.dict(os.environ, {}, clear=True):
        ...     read_settings()
        Traceback (most recent call last):
        ...
        RuntimeError: FACTORY_SIMULATOR_DATABASE_URL: Field required
    """
    try:
        # The required settings come from the environment, not from arguments.
        return Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        first = error.errors()[0]
        name = "FACTORY_SIMULATOR_" + str(first["loc"][0]).upper()
        problem = str(first["msg"]).removeprefix("Value error, ")
        raise RuntimeError(f"{name}: {problem}") from None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application.

    Args:
        settings (Settings | None, optional): The settings; read from the environment
            when the server starts when not given.

    Returns:
        FastAPI: The application, its routes under `/api/v1`.

    Examples:
        >>> from fastapi.testclient import TestClient
        >>> url = "duckdb:///:memory:create_app"
        >>> settings = Settings(database_url=url, load_examples=False)
        >>> with TestClient(create_app(settings)) as client:
        ...     client.get("/api/v1/manifests").json()
        {'manifests': []}
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app_settings = settings if settings is not None else read_settings()
        version = metadata.version("factory-simulator")
        database_engine = database.create_database_engine(app_settings.database_url)
        try:
            database.prepare(database_engine, version)
            recover_operations(database_engine)
            startup = create_operation(
                database_engine, None, None, None, kind="startup"
            )
            try:
                if app_settings.load_examples:
                    with Session(database_engine) as session:
                        create_examples(session)
                app.state.engine = database_engine
                app.state.server = Server(version=version)
            except BaseException as error:
                finish_operation(database_engine, startup, error)
                raise
            finish_operation(database_engine, startup)
            failure: BaseException | None = None
            try:
                yield
            except BaseException as error:
                failure = error
                raise
            finally:
                shutdown = create_operation(
                    database_engine, None, None, None, kind="shutdown"
                )
                finish_operation(database_engine, shutdown, failure)
        finally:
            database_engine.dispose()

    app = RecordedApplication(
        title="Factory simulator",
        version=metadata.version("factory-simulator"),
        lifespan=lifespan,
        openapi_url=PREFIX + "/openapi.json",
        docs_url=PREFIX + "/docs",
        redoc_url=None,
    )
    app.include_router(manifests.router, prefix=PREFIX)
    app.include_router(scenarios.router, prefix=PREFIX)
    app.include_router(runs.router, prefix=PREFIX)
    app.add_exception_handler(InputError, error_handler(422))
    app.add_exception_handler(NotFoundError, error_handler(404))
    app.add_exception_handler(ConflictError, error_handler(409))
    app.add_exception_handler(PoolTimeoutError, answer_pool_timeout)
    app.add_exception_handler(HTTPException, answer_route_error)
    # Starlette answers any other exception with this handler, then raises it on, so
    # the server logs its traceback.
    app.add_exception_handler(Exception, answer_defect)
    app.openapi = lambda: openapi_with_bodies(app)
    return app


def error_handler(status: int) -> Callable[[Request, Exception], Response]:
    """Give a handler that answers an error with a status and its text.

    Args:
        status (int): The status of the answer.

    Returns:
        Callable[[Request, Exception], Response]: The handler.

    Examples:
        >>> handle = error_handler(404)
        >>> error = NotFoundError("run_id: unknown run r-1")
        >>> response = handle(Request({"type": "http"}), error)
        >>> response.status_code, response.body
        (404, b'{"detail":"run_id: unknown run r-1"}')
    """

    def handle(request: Request, error: Exception) -> Response:  # noqa: ARG001
        return answer({"detail": str(error)}, status)

    return handle


def answer_pool_timeout(request: Request, error: Exception) -> Response:  # noqa: ARG001
    """Answer a request that found no free connection of the database with 503.

    Args:
        request (Request): The request.
        error (Exception): The timeout of the pool of connections.

    Returns:
        Response: 503 and the detail `database: no connection was free within 30 s`.

    Examples:
        >>> request = Request({"type": "http"})
        >>> response = answer_pool_timeout(request, PoolTimeoutError())
        >>> response.status_code, response.body
        (503, b'{"detail":"database: no connection was free within 30 s"}')
    """
    return answer({"detail": POOL_TIMEOUT_DETAIL}, 503)


def answer_route_error(request: Request, error: Exception) -> Response:  # noqa: ARG001
    """Answer a request that no route takes, such as an unknown path or method.

    Args:
        request (Request): The request.
        error (Exception): The `HTTPException` of Starlette, with its status and the
            phrase of that status.

    Returns:
        Response: The status of the error, `route: <the phrase in lower case>` as
            the detail, and the headers of the error, such as `allow` of a 405.

    Examples:
        >>> request = Request({"type": "http"})
        >>> response = answer_route_error(request, HTTPException(404))
        >>> response.status_code, response.body
        (404, b'{"detail":"route: not found"}')
    """
    route_error = cast(HTTPException, error)
    response = answer(
        {"detail": f"route: {route_error.detail.lower()}"}, route_error.status_code
    )
    response.headers.update(route_error.headers or {})
    return response


def answer_defect(request: Request, error: Exception) -> Response:  # noqa: ARG001
    """Answer an unexpected exception, a defect, with 500 and a fixed detail.

    Args:
        request (Request): The request.
        error (Exception): The exception; its text stays out of the answer.

    Returns:
        Response: 500 and the detail `server: internal error`.

    Examples:
        >>> request = Request({"type": "http"})
        >>> response = answer_defect(request, KeyError("secret"))
        >>> response.status_code, response.body
        (500, b'{"detail":"server: internal error"}')
    """
    return answer({"detail": DEFECT_DETAIL}, 500)


def openapi_with_bodies(app: FastAPI) -> dict[str, Any]:
    """Give the OpenAPI schema with the schemas of the bodies the routes read.

    FastAPI's own 422 answer of a route and its schemas `HTTPValidationError` and
    `ValidationError` are left out: every error answers `ErrorPublic`.

    Args:
        app (FastAPI): The application.

    Returns:
        dict[str, Any]: The OpenAPI schema.

    Examples:
        >>> schema = openapi_with_bodies(create_app())
        >>> "RunCreate" in schema["components"]["schemas"]
        True
        >>> "HTTPValidationError" in schema["components"]["schemas"]
        False
    """
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for methods in schema["paths"].values():
        for operation in methods.values():
            responses = operation["responses"]
            if "HTTPValidationError" in str(responses.get("422")):
                del responses["422"]
    _, definitions = models_json_schema(
        [(model, "validation") for model in BODY_MODELS],
        ref_template="#/components/schemas/{model}",
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    components.update(definitions.get("$defs", {}))
    app.openapi_schema = schema
    return schema


app = create_app()
