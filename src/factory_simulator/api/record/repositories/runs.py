"""The rows of runs: find a run, read and insert rows, sum the ledger, add interactions.

Examples:
    >>> from factory_simulator.api.record import database
    >>> database_engine = database.create_database_engine("duckdb:///:memory:")
    >>> database.prepare(database_engine, "0.1.0")
    >>> find_run(Session(database_engine), "r-1") is None
    True
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from factory_simulator.api.record.database import recorded_value
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.run import (
    Interaction,
    LedgerEntry,
    Measure,
    Run,
)
from factory_simulator.api.record.repositories import save


def find_run(session: Session, run_id: str) -> Run | None:
    """Find a stored run.

    Args:
        session (Session): The session; its caller commits.
        run_id (str): The identifier of the run.

    Returns:
        Run | None: The run, or None when there is none.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> find_run(session, "r-1") is None
        True
    """
    return session.get(Run, run_id)


def rows_by_period(
    session: Session, table: type[Base], run_id: str, last: int
) -> dict[int, list[dict[str, object]]]:
    """Give the rows of a table for the periods 1 to last of a run, with one query.

    Each row is the value of each column by its name; the rows of a period follow
    the primary key.

    Args:
        session (Session): The session; its caller commits.
        table (type[Base]): The mapped class of a table with a `period` column.
        run_id (str): The identifier of the run.
        last (int): The last period.

    Returns:
        dict[int, list[dict[str, object]]]: The rows by period, the periods in
            order; a period without rows is left out.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> from factory_simulator.api.services import scenarios
        >>> scenario_body = b'{"horizon": 3}'
        >>> manifest_id = manifest["id"]
        >>> _, scenario = scenarios.create_scenario(session, manifest_id, scenario_body)
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.runs import runs
        >>> from factory_simulator.api.services.runs.memory import Server
        >>> server = Server(version="0.1.0")
        >>> body = write_json({"scenario_id": scenario["id"], "seed": 7})
        >>> run = runs.start_run(server, session, body)
        >>> empty = b'{"period": %d, "decisions": []}'
        >>> for period in (1, 2, 3):
        ...     _ = runs.submit_decisions(server, session, run["id"], empty % period)
        >>> from factory_simulator.api.record.models.run import Period
        >>> rows = rows_by_period(session, Period, run["id"], 2)
        >>> [(period, row["period"]) for period, kept in rows.items() for row in kept]
        [(1, 1), (2, 2)]
    """
    columns = table.__table__.c
    statement = (
        select(*columns)
        .where(columns.run_id == run_id, columns.period.between(1, last))
        .order_by(*table.__table__.primary_key)
    )
    grouped: dict[int, list[dict[str, object]]] = {}
    for row in session.execute(statement).mappings():
        grouped.setdefault(cast(int, row["period"]), []).append(dict(row))
    return grouped


def insert_rows(
    session: Session, rows: Mapping[type[Base], list[dict[str, object]]]
) -> None:
    """Insert rows of the tables of a run in one statement per table.

    Args:
        session (Session): The session; its caller commits.
        rows (Mapping[type[Base], list[dict[str, object]]]): The values of each row
            by column, by table.

    Raises:
        ValueError: If a decimal of a row has more than 12 places, more than 26
            digits before the point in a typed column, or more than 50 digits as a
            whole decimal inside JSON.

    Examples:
        >>> rows = {LedgerEntry: [{"amount": Decimal("0.0000000000001")}]}
        >>> insert_rows(Session(), rows)
        Traceback (most recent call last):
        ...
        ValueError: ledger.amount: more than 12 places
    """
    for table, values in rows.items():
        name = table.__tablename__
        checked = [
            {
                column: recorded_value(f"{name}.{column}", value)
                for column, value in row.items()
            }
            for row in values
        ]
        if not checked:
            continue
        session.execute(insert(Base.metadata.tables[name]), checked)


def ledger_totals(session: Session, run_id: str) -> dict[str, Decimal]:
    """Give the sums of the ledger of a run by kind, rows not yet committed included.

    Args:
        session (Session): The session; its caller commits.
        run_id (str): The identifier of the run.

    Returns:
        dict[str, Decimal]: The total of each kind that has rows.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> from factory_simulator.api.services import scenarios
        >>> scenario_body = b'{"horizon": 3}'
        >>> manifest_id = manifest["id"]
        >>> _, scenario = scenarios.create_scenario(session, manifest_id, scenario_body)
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.runs import runs
        >>> from factory_simulator.api.services.runs.memory import Server
        >>> server = Server(version="0.1.0")
        >>> body = write_json({"scenario_id": scenario["id"], "seed": 7})
        >>> run = runs.start_run(server, session, body)
        >>> empty = b'{"period": %d, "decisions": []}'
        >>> for period in (1, 2, 3):
        ...     _ = runs.submit_decisions(server, session, run["id"], empty % period)
        >>> sorted(ledger_totals(session, run["id"]))
        ['interest_paid', 'late_penalty', 'lost_sale_penalty']
    """
    statement = (
        select(LedgerEntry.kind, func.sum(LedgerEntry.amount))
        .where(LedgerEntry.run_id == run_id)
        .group_by(LedgerEntry.kind)
    )
    return {kind: total for kind, total in session.execute(statement)}


def measure_rows(
    session: Session, run_id: str
) -> list[tuple[str, str, Decimal | None]]:
    """Give every measure of a run by period, rows not yet committed included.

    Args:
        session (Session): The session; its caller commits.
        run_id (str): The identifier of the run.

    Returns:
        list[tuple[str, str, Decimal | None]]: The name, key and value of each row,
            in period order.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> from factory_simulator.api.services import scenarios
        >>> scenario_body = b'{"horizon": 3}'
        >>> manifest_id = manifest["id"]
        >>> _, scenario = scenarios.create_scenario(session, manifest_id, scenario_body)
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.runs import runs
        >>> from factory_simulator.api.services.runs.memory import Server
        >>> server = Server(version="0.1.0")
        >>> body = write_json({"scenario_id": scenario["id"], "seed": 7})
        >>> run = runs.start_run(server, session, body)
        >>> empty = b'{"period": %d, "decisions": []}'
        >>> for period in (1, 2, 3):
        ...     _ = runs.submit_decisions(server, session, run["id"], empty % period)
        >>> measure_rows(session, run["id"])[0][:2]
        ('breakdowns', 'lines.final-assembly-line')
    """
    statement = (
        select(Measure.name, Measure.key, Measure.value)
        .where(Measure.run_id == run_id)
        .order_by(Measure.period, Measure.name, Measure.key)
    )
    return [(name, key, value) for name, key, value in session.execute(statement)]


def count_interactions(session: Session, run_id: str) -> int:
    """Give the number of interactions of a run.

    Args:
        session (Session): The session; its caller commits.
        run_id (str): The identifier of the run.

    Returns:
        int: The number of its rows in `interactions`.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> count_interactions(Session(database_engine), "r-1")
        0
    """
    count = session.scalar(
        select(func.count())
        .select_from(Interaction)
        .where(Interaction.run_id == run_id)
    )
    return count or 0


def add_interaction(
    session: Session,
    run_id: str,
    position: int,
    period: int,
    kind: Literal["check", "refusal"],
    submission: object,
    outcomes: object = None,
    refusal: str | None = None,
) -> None:
    """Add a check or a refused submission as an interaction and commit it.

    Args:
        session (Session): The session; the function commits.
        run_id (str): The identifier of the run.
        position (int): The position of the interaction among those of the run,
            from 1.
        period (int): The current period of the run.
        kind (Literal["check", "refusal"]): A check, or a refused submission.
        submission (object): The submission, validated or as received.
        outcomes (object, optional): The outcomes of a check; None when not given,
            as for a refusal.
        refusal (str | None, optional): Why the submission was refused; None when
            not given, as for a check.

    Raises:
        ValueError: If a decimal of the interaction has more than 12 places, or more
            than 50 digits as a whole decimal inside JSON.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services import manifests
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = manifests.create_manifest(session, manifest_body)
        >>> from factory_simulator.api.services import scenarios
        >>> scenario_body = b'{"horizon": 3}'
        >>> manifest_id = manifest["id"]
        >>> _, scenario = scenarios.create_scenario(session, manifest_id, scenario_body)
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.runs import runs
        >>> from factory_simulator.api.services.runs.memory import Server
        >>> server = Server(version="0.1.0")
        >>> body = write_json({"scenario_id": scenario["id"], "seed": 7})
        >>> run = runs.start_run(server, session, body)
        >>> add_interaction(
        ...     session, run["id"], 1, 1, "refusal", "{", refusal="not JSON"
        ... )
        >>> count_interactions(session, run["id"])
        1
    """
    interaction = Interaction(
        run_id=run_id,
        position=position,
        period=period,
        kind=kind,
        submission=submission,
        outcomes=outcomes,
        refusal=refusal,
    )
    save(session, interaction)
    session.commit()
