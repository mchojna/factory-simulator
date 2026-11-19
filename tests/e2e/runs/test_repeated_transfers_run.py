import io
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
from factories import (
    api_client,
    assert_run_balances,
    back_and_forth_transfers,
    get,
    start_run,
    submit,
    transfer,
    transfer_bound_bodies,
)


def ledger_of_export(content: bytes) -> list[tuple[Any, ...]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        ledger = archive.read("ledger.parquet")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.parquet"
        path.write_bytes(ledger)
        with duckdb.connect() as connection:
            relation = connection.read_parquet(str(path))
            return relation.project("period, kind, amount, cash_after").fetchall()


# Two periods of the world of repeated immediate transfers at a route cost of
# 5000000000000000000000: the 5001 transfers of period 1 move the chip once, and in
# period 2 it moves back.
@pytest.mark.slow
def test_a_chip_sent_back_in_the_period_after_5001_transfers_ends_the_run_exactly():
    with api_client() as client:
        run = start_run(
            client, *transfer_bound_bodies(2, "5000000000000000000000.0000")
        )
        first_status, second = submit(client, run["id"], 1, back_and_forth_transfers())
        last_status, finished = submit(
            client, run["id"], 2, [transfer("chip", "1", "annex", "main")]
        )
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
        exported = client.get(f"/api/v1/runs/{run['id']}/export")

    assert (first_status, second["period"], second["cash"]) == (
        200,
        2,
        -4999999999999999999000,
    )
    assert second["stock"]["annex"]["chip"] == 1
    assert (last_status, finished["finished"]) == (200, True)
    closing = periods["periods"][1]["steps"][-1]
    assert closing["state"]["cash"] == -9999999999999999999000
    measures = result["measures"]
    assert measures["total"]["transfer_cost"] == 10000000000000000000000
    assert measures["routes"]["main/annex"]["units_transferred"] == 1
    assert measures["routes"]["annex/main"]["units_transferred"] == 1
    assert_run_balances(periods, result)
    assert exported.status_code == 200
    assert ledger_of_export(exported.content) == [
        (
            1,
            "transfer_cost",
            Decimal("-5000000000000000000000.000000000000"),
            Decimal("-4999999999999999999000.000000000000"),
        ),
        (
            2,
            "transfer_cost",
            Decimal("-5000000000000000000000.000000000000"),
            Decimal("-9999999999999999999000.000000000000"),
        ),
    ]
