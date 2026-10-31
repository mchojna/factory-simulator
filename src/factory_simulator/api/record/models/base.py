"""The base of the mapped classes: the base class, exact decimals, the schema version.

Examples:
    >>> SchemaVersion(version="0.2.0").version
    '0.2.0'
"""

from decimal import Decimal

from sqlalchemy import Dialect, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ExactDecimal(Numeric[Decimal]):
    """A `Numeric` column whose decimals pass to and from the driver unchanged.

    Examples:
        >>> ExactDecimal(38, 12).scale
        12
    """

    cache_ok = True

    def bind_processor(self, dialect: Dialect) -> None:
        """Pass a decimal to the driver as it is.

        Args:
            dialect (Dialect): The dialect of the database.

        Examples:
            >>> from sqlalchemy.dialects import sqlite
            >>> print(ExactDecimal(38, 12).bind_processor(sqlite.dialect()))
            None
        """

    def result_processor(self, dialect: Dialect, coltype: object) -> None:
        """Take a decimal from the driver as it is.

        Args:
            dialect (Dialect): The dialect of the database.
            coltype (object): The type the driver reports.

        Examples:
            >>> from sqlalchemy.dialects import sqlite
            >>> print(ExactDecimal(38, 12).result_processor(sqlite.dialect(), None))
            None
        """


DECIMAL = ExactDecimal(38, 12)


class Base(DeclarativeBase):
    """The base of every mapped class of the record.

    Examples:
        >>> "schema_version" in Base.metadata.tables
        True
    """


class SchemaVersion(Base):
    """The version of the package that created the database.

    Attributes:
        version (str): The version, such as `0.2.0`.

    Examples:
        >>> SchemaVersion(version="0.2.0").version
        '0.2.0'
    """

    __tablename__ = "schema_version"

    version: Mapped[str] = mapped_column(String, primary_key=True)
