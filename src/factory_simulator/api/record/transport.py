"""The transport export: the operations of a stopped server and their bodies, checked.

Examples:
    >>> parquet_columns(OperationIdentity)
    ['"position"']
"""

import argparse
import hashlib
import shutil
import zipfile
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import cast

from sqlalchemy import JSON, URL, create_engine, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.record.database import canonical_text, read_column
from factory_simulator.api.record.models.base import Base, SchemaVersion
from factory_simulator.api.record.models.operation import (
    Operation,
    OperationBody,
    OperationIdentity,
)
from factory_simulator.api.record.repositories.operations import BODY_CHUNK_SIZE

# The files of operations in the export of a run and in the transport export.
OPERATION_FILES = (
    "operations.parquet",
    "operation_bodies.parquet",
    "operations.json",
)


def parquet_columns(table: type[Base]) -> list[str]:
    """Give quoted export columns, with JSON represented as UTF-8 text.

    Args:
        table (type[Base]): The mapped table.

    Returns:
        list[str]: SQL column expressions in mapped order.

    Examples:
        >>> parquet_columns(OperationIdentity)
        ['"position"']
    """
    return [
        f'CAST("{column.name}" AS VARCHAR) AS "{column.name}"'
        if isinstance(column.type, JSON)
        else f'"{column.name}"'
        for column in table.__table__.columns
    ]


def write_run_operations(session: Session, run_id: str, folder: Path) -> int:
    """Write the operations of a finished run and their bodies into a folder.

    The caller checks that the run is finished. The response of an earlier export of
    the run is written as a reference to its chunks, which stay in the database.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        folder (Path): The folder receiving the Parquet files and metadata.

    Returns:
        int: The operation cutoff, excluding the current export intent.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> from factory_simulator.api.record.database import (
        ...     create_database_engine,
        ...     prepare,
        ... )
        >>> database_engine = create_database_engine("duckdb:///:memory:run_operations")
        >>> prepare(database_engine, "0.1.0")
        >>> with TemporaryDirectory() as folder, Session(database_engine) as session:
        ...     write_run_operations(session, "r-1", Path(folder))
        0
    """
    operation = session.info.get("operation")
    if isinstance(operation, Operation):
        cutoff = operation.position - 1
    else:
        cutoff = session.scalar(select(func.max(OperationIdentity.position))) or 0
    parameters = (cutoff, run_id, run_id)
    predicate = "position <= ? AND (run_id = ? OR created_run_id = ?)"
    archives = "method = 'GET' AND status_code = 200 AND path LIKE '%/export'"
    identifiers = f"SELECT position FROM operations WHERE {predicate}"  # noqa: S608

    queries = {
        "operations.parquet": (
            f"SELECT {', '.join(parquet_columns(Operation))} FROM operations "  # noqa: S608
            f"WHERE {predicate} ORDER BY position"
        ),
        "operation_bodies.parquet": (
            f"SELECT {', '.join(parquet_columns(OperationBody))} FROM operation_bodies "  # noqa: S608
            f"WHERE operation_id IN ({identifiers}) "
            "AND NOT (direction = 'response' AND operation_id IN "
            f"(SELECT position FROM operations WHERE {archives})) "
            "ORDER BY operation_id, direction, position"
        ),
    }
    connection = session.connection()
    for filename, query in queries.items():
        target = str(folder / filename).replace("'", "''")
        connection.exec_driver_sql(
            f"COPY ({query}) TO '{target}' (FORMAT parquet)", parameters
        )
    references = connection.exec_driver_sql(
        "SELECT operation_id, direction, position, digest, octet_length(body) "  # noqa: S608
        "FROM operation_bodies WHERE direction = 'response' "
        f"AND operation_id IN (SELECT position FROM operations WHERE {predicate} "
        f"AND {archives}) ORDER BY operation_id, position",
        parameters,
    )
    operations_document = {
        "format": "factory-simulator-operations-v1",
        "kind": "run",
        "run_id": run_id,
        "cutoff": cutoff,
        "body_chunk_size": BODY_CHUNK_SIZE,
        "client_receipt": "unconfirmed",
        "external_bodies": [
            {
                "operation_id": row[0],
                "direction": row[1],
                "position": row[2],
                "digest": row[3],
                "size": row[4],
            }
            for row in references
        ],
    }
    (folder / "operations.json").write_bytes(write_json(operations_document))
    return cutoff


def export_transport(database_file: Path, destination: Path) -> Path:
    """Export and verify the complete transport record after the server stops.

    The input opens read-only with its matching schema. The bundle retains exact
    archive responses and operations with no run. An existing destination is refused.

    Args:
        database_file (Path): The stopped DuckDB database file.
        destination (Path): The new ZIP file.

    Returns:
        Path: The verified transport bundle.

    Raises:
        FileNotFoundError: If the database file does not exist.
        FileExistsError: If the destination already exists.
        RuntimeError: If the database and running package versions differ.
        ValueError: If a body or an archived reference fails verification.

    Examples:
        >>> export_transport(Path("missing.duckdb"), Path("transport.zip"))
        Traceback (most recent call last):
        ...
        FileNotFoundError: missing.duckdb
    """
    if not database_file.is_file():
        raise FileNotFoundError(database_file)
    if destination.exists():
        raise FileExistsError(destination)
    database_engine = create_engine(
        URL.create("duckdb", database=str(database_file.resolve())),
        connect_args={"read_only": True},
        json_serializer=canonical_text,
        json_deserializer=read_column,
    )
    try:
        with Session(database_engine) as session, TemporaryDirectory() as directory:
            folder = Path(directory)
            recorded = session.scalar(select(SchemaVersion.version))
            running = metadata.version("factory-simulator")
            if recorded != running:
                raise RuntimeError(
                    f"schema_version: database {recorded}, package {running}"
                )
            cutoff = session.scalar(select(func.max(OperationIdentity.position))) or 0
            chunks, references = verify_transport(session, cutoff)
            connection = session.connection()
            for table in (Operation, OperationBody):
                key = "position" if table is Operation else "operation_id"
                order = ", ".join(
                    f'"{column.name}"' for column in table.__table__.primary_key
                )
                target = str(folder / f"{table.__tablename__}.parquet").replace(
                    "'", "''"
                )
                connection.exec_driver_sql(
                    f"COPY (SELECT {', '.join(parquet_columns(table))} "  # noqa: S608
                    f"FROM {table.__tablename__} WHERE {key} <= ? ORDER BY {order}) "
                    f"TO '{target}' (FORMAT parquet)",
                    (cutoff,),
                )
            with database_file.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            operations_document: dict[str, object] = {
                "format": "factory-simulator-operations-v1",
                "kind": "transport",
                "cutoff": cutoff,
                "package_version": recorded,
                "database_sha256": digest,
                "body_chunk_size": BODY_CHUNK_SIZE,
                "client_receipt": "unconfirmed",
                "checked_body_chunks": chunks,
                "checked_archive_references": references,
                "external_bodies": [],
            }
            (folder / "operations.json").write_bytes(write_json(operations_document))
            archive_path = folder / "transport.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for filename in OPERATION_FILES:
                    archive.write(folder / filename, filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with destination.open("xb") as output:
                    created = True
                    with archive_path.open("rb") as source:
                        shutil.copyfileobj(source, output, length=BODY_CHUNK_SIZE)
            except BaseException:
                if created:
                    destination.unlink(missing_ok=True)
                raise
    finally:
        database_engine.dispose()
    return destination


def verify_transport(session: Session, cutoff: int) -> tuple[int, int]:
    """Verify that the transport bodies and references are complete and consistent.

    Args:
        session (Session): The read-only session of the stopped record.
        cutoff (int): The last operation included.

    Returns:
        tuple[int, int]: Verified chunk count and archive reference count.

    Raises:
        ValueError: If a digest, chunk order, complete length or reference differs.

    Examples:
        >>> from factory_simulator.api.record.database import (
        ...     create_database_engine,
        ...     prepare,
        ... )
        >>> database_engine = create_database_engine(
        ...     "duckdb:///:memory:verify_transport"
        ... )
        >>> prepare(database_engine, "0.1.0")
        >>> with Session(database_engine) as session:
        ...     verify_transport(session, 0)
        (0, 0)
    """
    identities = set(
        session.scalars(
            select(OperationIdentity.position).where(
                OperationIdentity.position <= cutoff
            )
        )
    )
    operation_positions = set(
        session.scalars(select(Operation.position).where(Operation.position <= cutoff))
    )
    if identities != operation_positions:
        raise ValueError("operation_identities: differ from the operations")
    invalid_body = session.scalar(
        select(OperationBody.operation_id)
        .where(
            OperationBody.operation_id <= cutoff,
            or_(
                OperationBody.direction.not_in(("request", "response")),
                func.octet_length(OperationBody.body) < 1,
                func.octet_length(OperationBody.body) > BODY_CHUNK_SIZE,
            ),
        )
        .limit(1)
    )
    if invalid_body is not None:
        raise ValueError("operation_bodies: a direction or a chunk size is not valid")
    totals: dict[tuple[int, str], tuple[int, int]] = {}
    chunks = 0
    bodies = (
        select(OperationBody)
        .where(OperationBody.operation_id <= cutoff)
        .order_by(
            OperationBody.operation_id, OperationBody.direction, OperationBody.position
        )
    )
    for body in session.scalars(bodies):
        key = (body.operation_id, body.direction)
        position, size = totals.get(key, (0, 0))
        if (
            body.position != position + 1
            or hashlib.sha256(body.body).hexdigest() != body.digest
        ):
            raise ValueError(
                f"operation_bodies: chunk {body.position} of {key} is not valid"
            )
        totals[key] = (body.position, size + len(body.body))
        chunks += 1
    operations = session.scalars(
        select(Operation).where(Operation.position <= cutoff)
    ).all()
    references = 0
    for operation in operations:
        for direction, complete, size in (
            ("request", operation.request_complete, operation.request_bytes),
            ("response", operation.response_generated, operation.response_bytes),
        ):
            if (
                complete
                and totals.get((operation.position, direction), (0, 0))[1] != size
            ):
                raise ValueError(
                    f"operation_bodies: the {direction} of {operation.position} "
                    "is not complete"
                )
        if (
            operation.method == "GET"
            and operation.status_code == 200
            and operation.path is not None
            and operation.path.endswith("/export")
            and operation.response_generated
        ):
            with TemporaryFile() as archive_body:
                response = (
                    select(OperationBody)
                    .where(
                        OperationBody.operation_id == operation.position,
                        OperationBody.direction == "response",
                    )
                    .order_by(OperationBody.position)
                )
                for body in session.scalars(response):
                    archive_body.write(body.body)
                archive_body.seek(0)
                try:
                    with zipfile.ZipFile(archive_body) as archive:
                        content = read_json_bytes(archive.read("operations.json"))
                except (zipfile.BadZipFile, KeyError) as error:
                    raise ValueError(
                        "transport: a generated archive is not valid"
                    ) from error
            references += verify_references(session, content, operation.position)
    return chunks, references


def verify_references(session: Session, content: object, operation_id: int) -> int:
    """Verify the external body references of the operations document of an export.

    Args:
        session (Session): The read-only session of the stopped record.
        content (object): The operations document read from the exported archive.
        operation_id (int): The position of the operation that answered the export.

    Returns:
        int: The number of verified references.

    Raises:
        ValueError: If the document, its cutoff or a reference is not valid, or a
            referenced body differs.

    Examples:
        >>> from factory_simulator.api.record.database import (
        ...     create_database_engine,
        ...     prepare,
        ... )
        >>> database_engine = create_database_engine(
        ...     "duckdb:///:memory:verify_references"
        ... )
        >>> prepare(database_engine, "0.1.0")
        >>> document = {"cutoff": 0, "external_bodies": []}
        >>> with Session(database_engine) as session:
        ...     verify_references(session, document, 1)
        0
    """
    if not isinstance(content, dict):
        raise ValueError("transport: an operations document is not valid")
    description = cast(dict[str, object], content)
    cutoff = description.get("cutoff")
    references = description.get("external_bodies")
    if (
        not isinstance(cutoff, int)
        or cutoff >= operation_id
        or not isinstance(references, list)
    ):
        raise ValueError("transport: an archive cutoff or its references are not valid")
    count = 0
    for value in cast(list[object], references):
        if not isinstance(value, dict):
            raise ValueError("transport: an external body reference is not valid")
        reference = cast(dict[str, object], value)
        linked = reference.get("operation_id")
        direction = reference.get("direction")
        position = reference.get("position")
        if (
            not isinstance(linked, int)
            or linked > cutoff
            or direction != "response"
            or not isinstance(position, int)
        ):
            raise ValueError("transport: an external body identity is not valid")
        body = session.get(OperationBody, (linked, direction, position))
        if (
            body is None
            or body.digest != reference.get("digest")
            or len(body.body) != reference.get("size")
        ):
            raise ValueError("transport: external body reference differs")
        count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export a stopped server's transport record."
    )
    parser.add_argument("database", type=Path, help="stopped DuckDB database file")
    parser.add_argument("output", type=Path, help="new transport ZIP file")
    arguments = parser.parse_args()
    try:
        export_transport(arguments.database, arguments.output)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        parser.exit(1, f"transport: {error}\n")
    print(arguments.output)
