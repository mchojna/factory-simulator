"""The database of the record: its engine, its preparation and the places it holds.

Examples:
    >>> read_column(canonical_text({"a": Decimal("1.50")}))
    {'a': Decimal('1.5')}
"""

from collections.abc import Mapping
from decimal import Context, Decimal, Inexact, InvalidOperation
from typing import cast

from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, inspect, make_url, select
from sqlalchemy.orm import Session

from factory_simulator.api.core.json import decimal_text, write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.record.models.base import Base, SchemaVersion
from factory_simulator.engine import CONTEXT

# DECIMAL(38, 12): 38 digits, 12 of them after the point. A decimal quantized to 12
# places in this context raises Inexact when it loses a digit, and InvalidOperation
# when it needs more than 38 digits.
RECORD_CONTEXT = Context(prec=38, traps=[Inexact, InvalidOperation])
TWELVE_PLACES = Decimal("1E-12")
# The seconds a request waits for a free connection of the pool.
POOL_TIMEOUT = 30
POOL_TIMEOUT_DETAIL = f"database: no connection was free within {POOL_TIMEOUT} s"


def create_database_engine(url: str) -> Engine:
    """Create the engine of a database, with JSON columns in canonical form.

    Args:
        url (str): A SQLAlchemy URL, such as `duckdb:///data/records/runs.duckdb`.

    Returns:
        Engine: The engine. JSON columns are written as canonical JSON and read with
            exact numbers. A request waits at most `POOL_TIMEOUT` seconds for a free
            connection of the pool.

    Examples:
        >>> create_database_engine("duckdb:///:memory:runs").pool.timeout()
        30
    """
    # An unnamed in-memory database keeps one connection per thread, without a
    # timeout.
    pool_options = (
        {} if make_url(url).database == ":memory:" else {"pool_timeout": POOL_TIMEOUT}
    )
    return create_engine(
        url,
        json_serializer=canonical_text,
        json_deserializer=read_column,
        **pool_options,
    )


def canonical_text(value: object) -> str:
    """Write a value as the canonical JSON text of a JSON column.

    Args:
        value (object): The value.

    Returns:
        str: Its canonical JSON.

    Examples:
        >>> canonical_text({"b": Decimal("1.50"), "a": 1})
        '{"a":1,"b":1.5}'
    """
    return write_json(value).decode("utf-8")


def read_column(text: str) -> object:
    """Read the text of a JSON column with exact numbers.

    Args:
        text (str): The JSON text.

    Returns:
        object: The value.

    Raises:
        InputError: If the text is not JSON or nested too deeply, or holds a number
            in another form, a constant such as `NaN`, a key twice, or text that is
            not valid Unicode; with its path.

    Examples:
        >>> read_column('{"a":1.5}')
        {'a': Decimal('1.5')}
    """
    return read_json_bytes(text.encode("utf-8"))


def prepare(database_engine: Engine, version: str) -> None:
    """Prepare a database: check its version, create its tables, write the version once.

    Args:
        database_engine (Engine): The engine of the database.
        version (str): The version of the package.

    Raises:
        RuntimeError: If the database was created by another version of the package.

    Examples:
        >>> database_engine = create_database_engine("duckdb:///:memory:")
        >>> prepare(database_engine, "0.1.0")
        >>> inspect(database_engine).has_table("runs")
        True
    """
    with Session(database_engine) as session:
        if inspect(database_engine).has_table(SchemaVersion.__tablename__):
            stored = session.scalars(select(SchemaVersion.version)).first()
            if stored is not None and stored != version:
                raise RuntimeError(
                    f"schema_version: database {stored}, package {version}"
                )
        Base.metadata.create_all(database_engine)
        if session.scalars(select(SchemaVersion.version)).first() is None:
            session.add(SchemaVersion(version=version))
            session.commit()


def recorded_value(column: str, value: object) -> object:
    """Give a value as the record holds it, or refuse a decimal it cannot hold.

    A decimal of a typed column is quantized to 12 places with a precision of 38
    digits, whatever the current context. A value of JSON is checked inside and given
    back unchanged.

    Args:
        column (str): The table and column, such as `ledger.amount`.
        value (object): A decimal, or models, mappings and lists holding decimals.

    Returns:
        object: A decimal with 12 places, or the value as given.

    Raises:
        ValueError: If a decimal has more than 12 places, a decimal of a typed
            column has more than 26 digits before the point, or a whole decimal
            inside JSON has more than 50 digits.

    Examples:
        >>> recorded_value("ledger.amount", Decimal("1.5000000000000"))
        Decimal('1.500000000000')
        >>> recorded_value("ledger.amount", Decimal("0.0000000000001"))
        Traceback (most recent call last):
        ...
        ValueError: ledger.amount: more than 12 places
    """
    if isinstance(value, Decimal):
        try:
            return value.quantize(TWELVE_PLACES, context=RECORD_CONTEXT)
        except Inexact:
            raise ValueError(f"{column}: more than 12 places") from None
        except InvalidOperation:
            raise ValueError(
                f"{column}: more than 26 digits before the point"
            ) from None
    check_json_places(column, value)
    return value


def check_json_places(column: str, value: object) -> None:
    """Refuse a decimal inside a value of JSON that the record cannot read back.

    Places are counted by value, after trailing zeros are removed. A whole decimal is
    written without a point, and the reader of a column takes such a number of at
    most 50 digits.

    Args:
        column (str): The table and column, such as `periods.state`.
        value (object): Models, mappings, lists and decimals.

    Raises:
        ValueError: If a decimal has more than 12 places, or a whole decimal has
            more than 50 digits.

    Examples:
        >>> check_json_places("periods.state", {"cash": Decimal("1" + "0" * 30)})
        >>> check_json_places("periods.state", [Decimal("0.1234567890123")])
        Traceback (most recent call last):
        ...
        ValueError: periods.state: more than 12 places
        >>> check_json_places("periods.state", {"cash": Decimal("1E+50")})
        Traceback (most recent call last):
        ...
        ValueError: periods.state: has more than 50 digits
    """
    if isinstance(value, Decimal):
        # A context as precise as the decimal removes its trailing zeros exactly.
        exact = Context(prec=max(1, len(value.as_tuple().digits)))
        exponent = value.normalize(exact).as_tuple().exponent
        if isinstance(exponent, int) and exponent < -12:
            raise ValueError(f"{column}: more than 12 places")
        text = decimal_text(value)
        if "." not in text and len(text.removeprefix("-")) > CONTEXT.prec:
            raise ValueError(f"{column}: has more than {CONTEXT.prec} digits")
    elif isinstance(value, BaseModel):
        check_json_places(column, value.model_dump(mode="python"))
    elif isinstance(value, Mapping):
        for item in cast(Mapping[object, object], value).values():
            check_json_places(column, item)
    elif isinstance(value, list | tuple):
        for item in cast(list[object] | tuple[object, ...], value):
            check_json_places(column, item)
