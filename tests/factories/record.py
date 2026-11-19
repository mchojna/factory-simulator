import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, inspect, select
from sqlalchemy.orm import Session

from factories.client import Client
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.run import (
    Event,
    LedgerEntry,
    Measure,
    Outcome,
    Period,
    Result,
    Run,
)
from factory_simulator.api.record.models.run import World as WorldRow
from factory_simulator.api.services.runs.memory import Server


# Every row of a run in every table but `interactions`, its identifier left out.
def rows_of_run(client: Client | TestClient, run_id: str) -> dict[str, list[Any]]:
    tables: tuple[type[Base], ...] = (
        Period,
        Event,
        LedgerEntry,
        Outcome,
        Measure,
        WorldRow,
        Result,
    )
    with Session(engine_of(client)) as session:
        rows = {
            table.__tablename__: [
                {key: value for key, value in row.items() if key != "run_id"}
                for row in rows_of_table(session, table, run_id=run_id)
            ]
            for table in tables
        }
        rows["runs"] = [
            {key: value for key, value in row.items() if key != "id"}
            for row in rows_of_table(session, Run, id=run_id)
        ]
    return rows


# The server of the application behind a test client.
def server_of(client: Client | TestClient) -> Server:
    app = cast(FastAPI, client.app)
    return cast(Server, app.state.server)


# The engine of the database of the application behind a test client.
def engine_of(client: Client | TestClient) -> Engine:
    app = cast(FastAPI, client.app)
    return cast(Engine, app.state.engine)


# The SQL statements the database of a client runs while `send` sends its requests.
def statements_of(client: Client, send: Callable[[], object]) -> list[str]:
    statements: list[str] = []

    def keep(*arguments: object) -> None:
        statements.append(str(arguments[2]))

    database = engine_of(client)
    event.listen(database, "before_cursor_execute", keep)
    try:
        send()
    finally:
        event.remove(database, "before_cursor_execute", keep)
    return statements


# Every row of a table with the given column values, by primary key.
def records(
    client: Client | TestClient, model: type[Base], **columns: object
) -> list[dict[str, Any]]:
    with Session(engine_of(client)) as session:
        return rows_of_table(session, model, **columns)


# The rows of a table as plain values, read with one select of its columns.
def rows_of_table(
    session: Session, model: type[Base], **columns: object
) -> list[dict[str, Any]]:
    mapper = inspect(model)
    keys = [column.key for column in mapper.column_attrs]
    statement = (
        select(*(getattr(model, key) for key in keys))
        .filter_by(**columns)
        .order_by(*mapper.primary_key)
    )
    return [dict(zip(keys, row, strict=True)) for row in session.execute(statement)]


# The URL of a database file in a new temporary directory, removed when the block ends.
@contextmanager
def database_file() -> Generator[str]:
    with tempfile.TemporaryDirectory() as directory:
        yield f"duckdb:///{Path(directory) / 'runs.duckdb'}"


# The measures of a period from rows of the table `measures`, nested as the periods
# of a run answer them.
def measures_of(rows: list[dict[str, Any]], period: int) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for row in rows:
        if row["period"] != period:
            continue
        group, _, key = row["key"].partition(".")
        place = nested.setdefault(group, {})
        if key:
            place = place.setdefault(key, {})
        place[row["name"]] = row["value"]
    return nested
