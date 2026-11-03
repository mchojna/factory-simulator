import os
import re
import unittest.mock
from importlib import metadata

import duckdb
import pytest
from factories import (
    api_client,
    database_file,
    get,
    post,
    tiny_manifest,
)
from fastapi.testclient import TestClient

from factory_simulator.api.main import create_app


def test_a_database_of_another_version_stops_the_start():
    with database_file() as url:
        connection = duckdb.connect(url.removeprefix("duckdb:///"))
        connection.execute("CREATE TABLE schema_version (version VARCHAR)")
        connection.execute("INSERT INTO schema_version VALUES ('0.0.0')")
        connection.close()
        running = metadata.version("factory-simulator")
        error = rf"^schema_version: database 0\.0\.0, package {re.escape(running)}$"
        with pytest.raises(RuntimeError, match=error), api_client(url):
            pass


def test_a_missing_database_setting_stops_the_start_with_its_name():
    with (
        unittest.mock.patch.dict(os.environ, clear=True),
        pytest.raises(
            RuntimeError, match=r"^FACTORY_SIMULATOR_DATABASE_URL: Field required$"
        ),
        TestClient(create_app()),
    ):
        pass


def test_two_applications_in_memory_do_not_share_their_records():
    with (
        api_client("duckdb:///:memory:first_of_two") as first,
        api_client("duckdb:///:memory:second_of_two") as second,
    ):
        post(first, "/manifests", tiny_manifest())
        _, listed = get(second, "/manifests")

    assert listed == {"manifests": []}


def test_a_test_after_another_in_the_same_process_starts_with_no_records():
    with api_client() as client:
        post(client, "/manifests", tiny_manifest())
    with api_client() as client:
        listed = get(client, "/manifests")

    assert listed == (200, {"manifests": []})
