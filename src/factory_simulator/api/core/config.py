"""The settings of the server: the variables FACTORY_SIMULATOR_* and their defaults.

Examples:
    >>> Settings(database_url="duckdb:///:memory:runs").database_url
    'duckdb:///:memory:runs'
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """The settings of the server.

    Attributes:
        database_url (str): The SQLAlchemy URL of the database, such as
            `duckdb:///data/records/runs.duckdb`; an in-memory database is named,
            such as `duckdb:///:memory:runs`.
        load_examples (bool, optional): Whether the examples are created at start.

    Examples:
        >>> Settings(database_url="duckdb:///:memory:runs").load_examples
        True
    """

    model_config = SettingsConfigDict(env_prefix="FACTORY_SIMULATOR_")

    database_url: str
    load_examples: bool = True

    @field_validator("database_url")
    @classmethod
    def check_database_named(cls, url: str) -> str:
        """Refuse an in-memory database without a name.

        Args:
            url (str): The SQLAlchemy URL of the database.

        Returns:
            str: The URL.

        Raises:
            ValueError: If the URL is `duckdb:///:memory:`.

        Examples:
            >>> Settings.check_database_named("duckdb:///:memory:runs")
            'duckdb:///:memory:runs'
        """
        if make_url(url).database == ":memory:":
            raise ValueError(
                "an in-memory database needs a name, such as duckdb:///:memory:runs"
            )
        return url
