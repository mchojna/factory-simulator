from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    assert_run_balances,
    buy,
    delivery_partition_bodies,
    get,
    item_balances,
    produce,
    rows_of_run,
    run_to_the_end,
    ship,
    start_run,
    yield_partition_bodies,
)

RECIPES = {"board": {"chip": Decimal(2)}, "monitor": {"board": Decimal(2)}}
START_STOCK = {"chip": Decimal(2), "board": Decimal(0), "monitor": Decimal(0)}
Decisions = dict[int, list[dict[str, Any]]]
ONE_BATCH = [produce("board", "1.000")]
SPLIT_BATCH = [produce("board", "0.001")] * 1000
THREE_TENTHS = {2: [produce("monitor", "0.300")], 3: [ship("order-0-1", "0.300")]}
HALF = {2: [produce("monitor", "0.500")], 3: [ship("order-0-1", "0.500")]}
POLICIES: dict[str, tuple[Decisions, Decimal]] = {
    "one_batch": ({1: ONE_BATCH} | THREE_TENTHS, Decimal("6.1")),
    "split_batch": ({1: SPLIT_BATCH} | THREE_TENTHS, Decimal("6.1")),
    "split_batch_and_half_a_monitor": ({1: SPLIT_BATCH} | HALF, Decimal("-10.7")),
}
ONE_BUY = [buy("1.000")]
SPLIT_BUY = [buy("0.001")] * 1000
BUYS: dict[str, Decisions] = {
    "one_buy_a_period": {1: ONE_BUY, 2: ONE_BUY},
    "split_buys_a_period": {1: SPLIT_BUY, 2: SPLIT_BUY},
}


@pytest.mark.slow
@pytest.mark.parametrize(
    ("decisions", "profit"), list(POLICIES.values()), ids=list(POLICIES)
)
def test_splitting_a_batch_of_boards_never_raises_the_profit(
    decisions: Decisions, profit: Decimal
):
    with api_client() as client:
        runs = [start_run(client, *yield_partition_bodies()) for _ in range(2)]
        for run in runs:
            run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{runs[0]['id']}/periods")
        _, result = get(client, f"/runs/{runs[0]['id']}/result")
        rows = [rows_of_run(client, run["id"]) for run in runs]

    assert result["profit"] == profit
    assert_run_balances(periods, result)
    into, out = item_balances(periods, RECIPES, START_STOCK)
    assert into == out
    assert rows[0] == rows[1]


@pytest.mark.slow
@pytest.mark.parametrize("decisions", list(BUYS.values()), ids=list(BUYS))
def test_splitting_buys_never_takes_more_than_the_delivery_limit(
    decisions: Decisions,
):
    with api_client() as client:
        run = start_run(client, *delivery_partition_bodies())
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    # At most 1 chip is bought a period and 0.6 of it arrives: 1.2 chips in periods 2
    # and 3, paid 1.2 * 0.5 = 0.6, kept for a salvage value of 1.2 * 0.1 = 0.12.
    assert result["profit"] == Decimal("-0.48")
    assert_run_balances(periods, result)
    into, out = item_balances(periods, RECIPES, dict.fromkeys(START_STOCK, Decimal(0)))
    assert into == out == {"chip": Decimal("1.2"), "board": 0, "monitor": 0}
