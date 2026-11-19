import pytest
from pydantic import ValidationError

from factory_simulator.api.core.config import Settings


def test_an_in_memory_database_without_a_name_is_refused():
    with pytest.raises(ValidationError, match="needs a name"):
        Settings(database_url="duckdb:///:memory:")
