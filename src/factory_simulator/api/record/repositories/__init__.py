"""The repositories of the record: one module per resource, and the save they share.

Examples:
    >>> from factory_simulator.api.record.models.run import Period
    >>> save(Session(), Period(run_id="r-1", period=1))
"""

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from factory_simulator.api.record.database import recorded_value
from factory_simulator.api.record.models.base import Base


def save(session: Session, *rows: Base) -> None:
    """Save rows: check the places of every column, keep them as checked, add the rows.

    Args:
        session (Session): The session; its caller commits.
        *rows (Base): The rows, new or changed.

    Raises:
        ValueError: If a decimal of a row has more than 12 places, more than 26
            digits before the point in a typed column, or more than 50 digits as a
            whole decimal inside JSON.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.api.record.models.run import LedgerEntry
        >>> save(Session(), LedgerEntry(amount=Decimal("0.0000000000001")))
        Traceback (most recent call last):
        ...
        ValueError: ledger.amount: more than 12 places
    """
    for row in rows:
        table = row.__tablename__
        for column in inspect(type(row)).column_attrs:
            value = recorded_value(f"{table}.{column.key}", getattr(row, column.key))
            setattr(row, column.key, value)
    session.add_all(rows)


def add_once(session: Session, row: Base, identifier: str) -> bool:
    """Add and commit a row unless a row with its identifier is stored.

    Two requests that add the same row at once both pass the first look; the commit
    of the one that loses fails, and it then finds the stored row.

    Args:
        session (Session): The session; the function commits.
        row (Base): The new row.
        identifier (str): Its primary key.

    Returns:
        bool: True when the row is new, False when it was stored.

    Raises:
        IntegrityError: If the commit fails and no row is stored.
        OperationalError: If the commit fails and no row is stored.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.record.models.manifest import Manifest
        >>> add_once(session, Manifest(id="m-1", content={}, linear=True), "m-1")
        True
        >>> add_once(session, Manifest(id="m-1", content={}, linear=True), "m-1")
        False
    """
    if session.get(type(row), identifier) is not None:
        return False
    save(session, row)
    try:
        session.commit()
    except IntegrityError, OperationalError:
        session.rollback()
        if session.get(type(row), identifier) is None:
            raise
        return False
    return True
