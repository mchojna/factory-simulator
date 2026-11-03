"""The recorder of operations: each request and its response, with their exact bytes.

Examples:
    >>> operation_time().endswith("+00:00")
    True
"""

import logging
from tempfile import TemporaryFile
from time import monotonic_ns
from typing import cast

from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from factory_simulator.api.record.database import POOL_TIMEOUT_DETAIL
from factory_simulator.api.record.repositories.operations import (
    BODY_CHUNK_SIZE,
    append_body,
    create_operation,
    finish_operation,
    operation_time,
    write_operation,
)
from factory_simulator.api.routes import answer

LOGGER = logging.getLogger(__name__)

PROTOCOL_HEADERS = frozenset(
    {
        b"host",
        b"accept",
        b"accept-encoding",
        b"content-type",
        b"content-length",
        b"content-disposition",
        b"user-agent",
        b"allow",
        b"location",
        b"etag",
        b"last-modified",
        b"cache-control",
        b"x-correlation-id",
        b"x-request-id",
    }
)


class RecordedApplication(FastAPI):
    """The application whose outer stack captures server error responses too.

    Examples:
        >>> isinstance(RecordedApplication(), FastAPI)
        True
    """

    def build_middleware_stack(self) -> ASGIApp:
        """Build the whole stack inside the recorder of operations.

        Returns:
            ASGIApp: The recorder around routing and error handling.

        Examples:
            >>> callable(RecordedApplication().build_middleware_stack())
            True
        """
        return record_operations(super().build_middleware_stack())


def record_operations(app: ASGIApp) -> ASGIApp:
    """Give the recorder of operations around an application.

    The recorder writes each HTTP request and its response, with their exact bytes,
    as an operation of the record. A request whose operation cannot be written is
    answered 503.

    Args:
        app (ASGIApp): The application to record.

    Returns:
        ASGIApp: The recorder around the application.

    Examples:
        >>> callable(record_operations(FastAPI()))
        True
    """

    async def recorded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        application = cast(FastAPI, scope["app"])
        database_engine = cast(Engine, application.state.engine)
        correlation = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"x-correlation-id"
            ),
            None,
        )
        started_nanoseconds = monotonic_ns()
        received_at = operation_time()
        try:
            operation = await run_in_threadpool(
                create_operation,
                database_engine,
                scope["method"],
                scope["path"],
                correlation,
                received_at=received_at,
            )
            operation.raw_path = scope.get("raw_path")
            operation.query = scope.get("query_string", b"")
            operation.request_headers = protocol_headers(scope.get("headers", []))
            await run_in_threadpool(write_operation, database_engine, operation)
        except SQLAlchemyError as error:
            LOGGER.exception("operation intent could not be stored")
            detail = (
                POOL_TIMEOUT_DETAIL
                if isinstance(error, PoolTimeoutError)
                else "database: operational record unavailable"
            )
            await answer({"detail": detail}, 503)(scope, receive, send)
            return
        scope.setdefault("state", {})["operation"] = operation
        failure: BaseException | None = None
        response_position = 0
        generated_bytes = 0
        try:
            with TemporaryFile() as request_body:
                request_position = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        operation.state = "interrupted"
                        return
                    body = message.get("body", b"")
                    request_position = await run_in_threadpool(
                        append_body,
                        database_engine,
                        operation.position,
                        "request",
                        request_position,
                        body,
                    )
                    await run_in_threadpool(request_body.write, body)
                    if not message.get("more_body", False):
                        break
                operation.request_complete = True
                request_length = request_body.tell()
                operation.request_bytes = request_length
                await run_in_threadpool(write_operation, database_engine, operation)
                request_body.seek(0)
                request_finished = False

                async def replay_request() -> Message:
                    nonlocal request_finished
                    if request_finished:
                        return await receive()
                    body = await run_in_threadpool(request_body.read, BODY_CHUNK_SIZE)
                    more = request_body.tell() < request_length
                    request_finished = not more
                    return {"type": "http.request", "body": body, "more_body": more}

                async def capture_response(message: Message) -> None:
                    nonlocal response_position, generated_bytes
                    body = b""
                    if message["type"] == "http.response.start":
                        operation.status_code = message["status"]
                        operation.response_headers = protocol_headers(
                            message.get("headers", [])
                        )
                    elif message["type"] == "http.response.body":
                        body = message.get("body", b"")
                        response_position = await run_in_threadpool(
                            append_body,
                            database_engine,
                            operation.position,
                            "response",
                            response_position,
                            body,
                        )
                        generated_bytes += len(body)
                        if not message.get("more_body", False):
                            operation.response_generated = True
                            operation.response_bytes = generated_bytes
                            operation.generated_at = operation_time()
                    await run_in_threadpool(write_operation, database_engine, operation)
                    try:
                        await send(message)
                    except BaseException:
                        if message["type"] == "http.response.start":
                            operation.headers_attempted = True
                        elif message["type"] == "http.response.body":
                            operation.attempted_bytes += len(body)
                        operation.state = "interrupted"
                        raise
                    if message["type"] == "http.response.start":
                        operation.headers_attempted = True
                        operation.headers_sent = True
                    elif message["type"] == "http.response.body":
                        operation.attempted_bytes += len(body)
                        operation.sent_bytes += len(body)
                    await run_in_threadpool(write_operation, database_engine, operation)

                await app(scope, replay_request, capture_response)
                operation.state = "completed"
        except BaseException as error:
            failure = error
            raise
        finally:
            route_name = getattr(scope.get("route"), "name", None)
            if isinstance(route_name, str):
                placeholders = {
                    key: "{" + key + "}" for key in scope.get("path_params", {})
                }
                operation.route = str(
                    application.url_path_for(route_name, **placeholders)
                )
            else:
                for candidate in application.routes:
                    if isinstance(candidate, Route) and candidate.matches(scope)[0] in (
                        Match.FULL,
                        Match.PARTIAL,
                    ):
                        operation.route = candidate.path_format
                        break
            operation.duration_ns = monotonic_ns() - started_nanoseconds
            await run_in_threadpool(
                finish_operation, database_engine, operation, failure
            )

    return recorded


def protocol_headers(headers: list[tuple[bytes, bytes]]) -> list[tuple[str, str]]:
    r"""Give the selected protocol headers with lossless Latin-1 byte encoding.

    Args:
        headers (list[tuple[bytes, bytes]]): The headers in ASGI order.

    Returns:
        list[tuple[str, str]]: Only declared protocol fields, with duplicates retained.

    Examples:
        >>> kept = protocol_headers(
        ...     [(b"authorization", b"hidden"), (b"user-agent", b"\xff")]
        ... )
        >>> kept[0][1].encode("latin-1")
        b'\xff'
    """
    return [
        (name.decode("latin-1"), value.decode("latin-1"))
        for name, value in headers
        if name.lower() in PROTOCOL_HEADERS
    ]
