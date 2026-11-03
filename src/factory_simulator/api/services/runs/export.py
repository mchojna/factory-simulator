"""The export of a finished run: a ZIP of its tables, its operations and its inputs.

Examples:
    >>> run_row_json(Run(id="r-1", seed="7"))["seed"]
    7
"""

import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.run import Interaction, Result, Run, World
from factory_simulator.api.record.transport import (
    OPERATION_FILES,
    parquet_columns,
    write_run_operations,
)
from factory_simulator.api.services.runs.rows import PERIOD_TABLES
from factory_simulator.api.services.runs.stored import finished_run

# The tables of a run written as Parquet by an export, in the order of the record.
EXPORTED_TABLES: tuple[type[Base], ...] = (*PERIOD_TABLES, World, Result, Interaction)


def export_run(session: Session, run_id: str, folder: Path) -> Path:
    """Export a finished run: write its ZIP file into a folder.

    It holds `<table>.parquet` for each table of the run, written by DuckDB with JSON
    columns as text; the operations of the run as `operations.parquet`,
    `operation_bodies.parquet` and `operations.json`; and `manifest.json`,
    `scenario.json` and `run.json` in canonical JSON.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        folder (Path): An empty folder the files are written into.

    Returns:
        Path: The ZIP file, `<run id>.zip`.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> export_run(session, "r-1", Path("."))
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = finished_run(session, run_id)
    connection = session.connection()
    for table in EXPORTED_TABLES:
        path = folder / f"{table.__tablename__}.parquet"
        connection.exec_driver_sql(parquet_copy(table, path), (run_id,))
    write_run_operations(session, run_id, folder)
    texts = {
        "manifest.json": run.scenario.manifest.content,
        "scenario.json": run.scenario.content,
        "run.json": run_row_json(run),
    }
    archive_path = folder / f"{run_id}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for table in EXPORTED_TABLES:
            name = f"{table.__tablename__}.parquet"
            archive.write(folder / name, name)
        for name in OPERATION_FILES:
            archive.write(folder / name, name)
        for name, value in texts.items():
            archive.writestr(name, write_json(value))
    return archive_path


def parquet_copy(table: type[Base], path: Path) -> str:
    """Give the DuckDB statement that writes the rows of one run of a table as Parquet.

    The statement takes the run identifier as its one parameter. JSON columns are
    written as text; rows are in the order of the primary key.

    Args:
        table (type[Base]): The mapped class of the table.
        path (Path): The Parquet file to write.

    Returns:
        str: The `COPY (SELECT ...) TO ... (FORMAT parquet)` statement.

    Examples:
        >>> statement = parquet_copy(World, Path("worlds.parquet"))
        >>> statement.endswith("TO 'worlds.parquet' (FORMAT parquet)")
        True
    """
    columns = parquet_columns(table)
    order = ", ".join(f'"{column.name}"' for column in table.__table__.primary_key)
    target = str(path).replace("'", "''")
    return (
        f"COPY (SELECT {', '.join(columns)} FROM {table.__tablename__} "  # noqa: S608
        f"WHERE run_id = ? ORDER BY {order}) TO '{target}' (FORMAT parquet)"
    )


def run_row_json(run: Run) -> dict[str, object]:
    """Write the row of a run for its export, the seed as a whole number.

    Args:
        run (Run): The run.

    Returns:
        dict[str, object]: Every column of the row, `description` as an object.

    Examples:
        >>> run_row_json(Run(id="r-1", seed="7"))["seed"]
        7
    """
    row: dict[str, object] = {
        column.key: getattr(run, column.key) for column in Run.__table__.columns
    }
    row["seed"] = int(run.seed)
    return row
