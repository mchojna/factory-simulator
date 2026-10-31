import os
from unittest import mock

import pytest

from factory_simulator.api.main import read_settings


def test_an_in_memory_database_without_a_name_stops_the_start_with_its_variable():
    url = {"FACTORY_SIMULATOR_DATABASE_URL": "duckdb:///:memory:"}

    with mock.patch.dict(os.environ, url), pytest.raises(RuntimeError) as refusal:
        read_settings()

    assert str(refusal.value).startswith("FACTORY_SIMULATOR_DATABASE_URL:")


def test_the_start_up_error_of_an_unnamed_in_memory_database_gives_a_named_example():
    url = {"FACTORY_SIMULATOR_DATABASE_URL": "duckdb:///:memory:"}

    with mock.patch.dict(os.environ, url), pytest.raises(RuntimeError) as refusal:
        read_settings()

    assert str(refusal.value) == (
        "FACTORY_SIMULATOR_DATABASE_URL: an in-memory database needs a name, "
        "such as duckdb:///:memory:runs"
    )
