from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    LIBRARY,
    Client,
    api_client,
    assert_run_balances,
    example_decisions,
    get,
    is_recovered,
    post,
    recovery_decisions,
    rows_of_run,
    stock_sale_decisions,
    submit,
)


def scenario_id(client: Client, name: str) -> str:
    _, manifests = get(client, "/manifests")
    [manifest] = manifests["manifests"]
    _, listed = get(client, f"/manifests/{manifest['id']}/scenarios")
    [found] = [scenario for scenario in listed["scenarios"] if scenario["name"] == name]
    return found["id"]


def drive(
    client: Client, name: str, decisions: dict[int, list[Any]]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    scenario = scenario_id(client, name)
    _, run = post(client, "/runs", {"scenario_id": scenario, "seed": 9})
    _, observation = get(client, f"/runs/{run['id']}/observation")
    while not observation.get("finished", False):
        period = observation["period"]
        status, observation = submit(
            client, run["id"], period, decisions.get(period, [])
        )
        assert status == 200, observation
    _, result = get(client, f"/runs/{run['id']}/result")
    _, periods = get(client, f"/runs/{run['id']}/periods")
    return run["id"], result, periods


@pytest.mark.slow
@pytest.mark.parametrize("name", LIBRARY)
def test_every_scenario_runs_a_fixed_decision_list_balances_and_repeats(name: str):
    decisions = {period: example_decisions(period) for period in range(1, 53)}
    with api_client(load_examples=True) as client:
        first, result, periods = drive(client, name, decisions)
        second, _, _ = drive(client, name, decisions)
        rows = [rows_of_run(client, run_id) for run_id in (first, second)]

    assert_run_balances(periods, result)
    for table in rows[0]:
        if table != "interactions":
            assert rows[0][table] == rows[1][table], table
    if name == "cash-squeeze":
        refused = result["measures"]["reasons"]["over_credit_limit"]
        assert refused["decisions_rejected"] > 0
    if name == "steady-market":
        kinds = {row["kind"] for row in rows[0]["ledger"]}
        assert "changeover_cost" in kinds


# The play of a scenario of the library on seed 0 with decisions drawn from each
# observation: the profit, the units shipped after period 20 and every buy as its
# accepted flag and reason.
def play(
    client: Client,
    name: str,
    policy: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> tuple[Decimal, Decimal, list[tuple[bool, str | None]]]:
    _, run = post(
        client, "/runs", {"scenario_id": scenario_id(client, name), "seed": 0}
    )
    _, observation = get(client, f"/runs/{run['id']}/observation")
    late = Decimal(0)
    buys: list[tuple[bool, str | None]] = []
    while not observation.get("finished", False):
        period = observation["period"]
        _, observation = submit(client, run["id"], period, policy(observation))
        for outcome in observation.get("outcomes", []):
            decision = outcome["decision"]
            if decision["kind"] == "buy":
                buys.append((outcome["accepted"], outcome.get("reason")))
            if decision["kind"] == "ship" and outcome["accepted"] and period > 20:
                late += Decimal(str(decision["quantity"]))
    _, result = get(client, f"/runs/{run['id']}/result")
    return result["profit"], late, buys


@pytest.mark.slow
def test_the_squeeze_recovers_and_buys_again_where_a_stock_sale_only_liquidates():
    with api_client(load_examples=True) as client:
        nothing = play(client, "cash-squeeze", lambda _: [])
        sale = play(client, "cash-squeeze", stock_sale_decisions)
        recovery = play(client, "cash-squeeze", recovery_decisions)
        control = play(client, "steady-market", recovery_decisions)

    # The stock sale is scorable: it earns more than no decisions, buys nothing and
    # ships nothing after period 20, once its stock is sold.
    assert sale[0] > nothing[0]
    assert (sale[1], sale[2]) == (0, [])
    # The recovery is refused for credit first, then buys again, ships from what it
    # buys and earns more than the stock sale.
    assert is_recovered(recovery[2])
    assert recovery[1] > 0
    assert recovery[0] > sale[0]
    # The steady market, with the same decisions, buys from period 1 and earns more.
    assert recovery[2][0] == (False, "over_credit_limit")
    assert control[2][0] == (True, None)
    assert control[0] > recovery[0]
