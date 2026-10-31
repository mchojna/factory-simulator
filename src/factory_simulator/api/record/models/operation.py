"""The mapped classes of operations: an operation, its identity and its body chunks.

Examples:
    >>> Operation.__tablename__
    'operations'
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    LargeBinary,
    Sequence,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from factory_simulator.api.record.models.base import Base


class OperationIdentity(Base):
    """The identity an operation shares with its body chunks.

    Attributes:
        position (int): The order of the operation in the record, from 1.

    Examples:
        >>> OperationIdentity(position=1).position
        1
    """

    __tablename__ = "operation_identities"

    position: Mapped[int] = mapped_column(
        Integer, Sequence("operation_positions"), primary_key=True
    )


class Operation(Base):
    """An operation of the server: a request and its response, a startup or a shutdown.

    Attributes:
        position (int): The order of the operation in the record, from 1.
        request_id (str): The unique identifier of the request.
        kind (str): The kind: `http`, `startup` or `shutdown`.
        correlation_id (str | None): The correlation identifier the client sends.
        method (str | None): The HTTP method.
        path (str | None): The requested path.
        raw_path (bytes | None): The exact encoded path, when ASGI gives it.
        query (bytes | None): The exact bytes of the query.
        request_headers (object): The selected protocol headers of the request, in
            their order and with their exact bytes.
        response_headers (object): The selected protocol headers the response sends.
        route (str | None): The matched route template, absent for an unknown route.
        manifest_id (str | None): The identifier of the manifest, when it is known.
        scenario_id (str | None): The identifier of the scenario, when it is known.
        requested_run_id (str | None): The identifier of the run in the path, even
            when it is unknown.
        run_id (str | None): The identifier of the run when it exists.
        created_run_id (str | None): The identifier of the run the operation creates.
        state (str): The state: `received`, `completed`, `failed` or `interrupted`.
        status_code (int | None): The status of the response.
        started_at (str): The UTC time of receipt, in ISO format.
        generated_at (str | None): The UTC time the complete response body is
            generated.
        finished_at (str | None): The UTC time the processing ends.
        recovered_at (str | None): The UTC time a startup finds the operation
            unfinished.
        duration_ns (int | None): The time of the processing, in nanoseconds.
        request_bytes (int | None): The length of the complete request, when it is
            known.
        response_bytes (int | None): The length of the complete generated response,
            when it is known.
        request_complete (bool): Whether the complete request body is captured.
        response_generated (bool): Whether the complete response body is generated.
        headers_attempted (bool): Whether the send of the response headers starts.
        headers_sent (bool): Whether the send of the response headers returns.
        attempted_bytes (int): The body bytes whose send starts.
        sent_bytes (int): The body bytes whose send returns, whether or not the client
            receives them.
        exception_type (str | None): The fully qualified type of the exception.
        exception_message (str | None): The text of the exception.
        exception_traceback (str | None): The traceback of the exception.

    Examples:
        >>> Operation(kind="http", state="received").state
        'received'
    """

    __tablename__ = "operations"

    position: Mapped[int] = mapped_column(
        ForeignKey("operation_identities.position"), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str | None] = mapped_column(String)
    method: Mapped[str | None] = mapped_column(String)
    path: Mapped[str | None] = mapped_column(String)
    raw_path: Mapped[bytes | None] = mapped_column(LargeBinary)
    query: Mapped[bytes | None] = mapped_column(LargeBinary)
    request_headers: Mapped[object] = mapped_column(JSON)
    response_headers: Mapped[object] = mapped_column(JSON)
    route: Mapped[str | None] = mapped_column(String)
    manifest_id: Mapped[str | None] = mapped_column(ForeignKey("manifests.id"))
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    requested_run_id: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    created_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    state: Mapped[str] = mapped_column(String)
    status_code: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str] = mapped_column(String)
    generated_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)
    recovered_at: Mapped[str | None] = mapped_column(String)
    duration_ns: Mapped[int | None] = mapped_column(BigInteger)
    request_bytes: Mapped[int | None] = mapped_column(BigInteger)
    response_bytes: Mapped[int | None] = mapped_column(BigInteger)
    request_complete: Mapped[bool] = mapped_column(Boolean)
    response_generated: Mapped[bool] = mapped_column(Boolean)
    headers_attempted: Mapped[bool] = mapped_column(Boolean)
    headers_sent: Mapped[bool] = mapped_column(Boolean)
    attempted_bytes: Mapped[int] = mapped_column(BigInteger)
    sent_bytes: Mapped[int] = mapped_column(BigInteger)
    exception_type: Mapped[str | None] = mapped_column(String)
    exception_message: Mapped[str | None] = mapped_column(String)
    exception_traceback: Mapped[str | None] = mapped_column(String)


class OperationBody(Base):
    r"""A chunk of the body of a request or a response, of at most 65536 bytes.

    Attributes:
        operation_id (int): The position of the operation.
        direction (str): The direction: `request` or `response`.
        position (int): The order of the chunk in its direction, from 1.
        body (bytes): The exact bytes of the chunk.
        digest (str): The SHA-256 digest of the bytes, in 64 hexadecimal digits.

    Examples:
        >>> OperationBody(direction="request", position=1, body=b" \xff").body
        b' \xff'
    """

    __tablename__ = "operation_bodies"

    operation_id: Mapped[int] = mapped_column(
        ForeignKey("operation_identities.position"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    digest: Mapped[str] = mapped_column(String)
