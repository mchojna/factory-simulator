"""The dependencies of the routes: the session of a request, the server, the body.

Examples:
    >>> from fastapi import FastAPI
    >>> (app := FastAPI()).state.server = Server(version="0.1.0")
    >>> get_server(Request({"type": "http", "app": app})).version
    '0.1.0'
"""

from collections.abc import Generator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from factory_simulator.api.record.models.operation import Operation
from factory_simulator.api.services.runs.memory import Server


def get_session(request: Request) -> Generator[Session]:
    """Give the request its own session of the database, closed when its route returns.

    Args:
        request (Request): The request.

    Yields:
        Session: The session. What it has not committed is rolled back at the end.

    Examples:
        >>> from fastapi import FastAPI
        >>> from sqlalchemy import create_engine
        >>> app = FastAPI()
        >>> app.state.engine = create_engine("duckdb:///:memory:")
        >>> sessions = get_session(Request({"type": "http", "app": app}))
        >>> next(sessions).bind is app.state.engine
        True
        >>> sessions.close()
    """
    database_engine = cast(Engine, request.app.state.engine)
    with Session(database_engine, expire_on_commit=False) as session:
        session.info["operation"] = request.scope.get("state", {}).get("operation")
        yield session


def get_server(request: Request) -> Server:
    """Give the server of the application.

    Args:
        request (Request): The request.

    Returns:
        Server: The server the lifespan made.

    Examples:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> app.state.server = Server(version="0.2.0")
        >>> get_server(Request({"type": "http", "app": app})).version
        '0.2.0'
    """
    return cast(Server, request.app.state.server)


async def read_body(request: Request) -> bytes:
    """Read the raw bytes of the body of a request.

    Args:
        request (Request): The request.

    Returns:
        bytes: The body as sent.

    Examples:
        >>> import asyncio
        >>> async def receive() -> dict[str, object]:
        ...     return {"type": "http.request", "body": b"{}", "more_body": False}
        >>> asyncio.run(read_body(Request({"type": "http"}, receive)))
        b'{}'
    """
    return await request.body()


def link_resources(
    session: Session,
    *,
    manifest_id: str | None = None,
    scenario_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Link resource identifiers returned by a creation route to its operation.

    The detached operation is persisted by the recorder after the route returns.
    This function opens no connection and changes no simulation row.

    Args:
        session (Session): The session of the request.
        manifest_id (str | None, optional): The known manifest; None when not
            given.
        scenario_id (str | None, optional): The known scenario; None when not
            given.
        run_id (str | None, optional): The known run; None when not given.

    Examples:
        >>> session = Session()
        >>> operation = Operation(kind="http", state="received")
        >>> session.info["operation"] = operation
        >>> link_resources(session, run_id="r-1")
        >>> operation.run_id
        'r-1'
    """
    operation = session.info.get("operation")
    if isinstance(operation, Operation):
        if manifest_id is not None:
            operation.manifest_id = manifest_id
        if scenario_id is not None:
            operation.scenario_id = scenario_id
        if run_id is not None:
            if operation.run_id is None:
                operation.run_id = run_id
            operation.created_run_id = run_id


SessionDependency = Annotated[Session, Depends(get_session, scope="function")]
ServerDependency = Annotated[Server, Depends(get_server)]
BodyDependency = Annotated[bytes, Depends(read_body)]
