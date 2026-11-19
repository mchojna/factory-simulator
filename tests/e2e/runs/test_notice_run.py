from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    rows_of_run,
    start_run,
    submit,
    tiny_scenario,
)

HORIZON = 12
SHARED: dict[int, list[dict[str, Any]]] = {1: [buy("50")], 2: [], 3: [buy("50")]}
STOCKING_UP: dict[int, list[dict[str, Any]]] = {
    period: [buy("50")] for period in range(4, 8)
}


def run_with_notice(
    notice: int, decisions: dict[int, list[dict[str, Any]]]
) -> tuple[dict[str, list[Any]], dict[int, Any], Decimal]:
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"]["main"]["chip"] = "0"
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 8,
            "duration": 4,
            "strength": "0.8000",
            "notice": notice,
        }
    ]
    seen: dict[int, Any] = {}
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=1)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period in range(1, HORIZON + 1):
            seen[period] = observation
            status, observation = submit(
                client, run["id"], period, decisions.get(period, [])
            )
            assert status == 200, observation
        rows = rows_of_run(client, run["id"])
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    assert_run_balances(periods, result)
    arrived = sum(
        (
            period["steps"][-1]["measures"]["suppliers"]["chip-maker/chip"][
                "units_arrived"
            ]
            for period in periods["periods"]
        ),
        Decimal(0),
    )
    return rows, seen, arrived


def early(rows: dict[str, list[Any]], name: str) -> list[Any]:
    return [row for row in rows[name] if row["period"] <= 3]


def test_a_notice_lets_the_agent_stock_up_before_an_outage():
    plain_rows, plain_seen, plain_arrived = run_with_notice(0, SHARED)
    rows, seen, arrived = run_with_notice(4, SHARED | STOCKING_UP)

    for name in ("ledger", "events", "outcomes", "measures"):
        assert early(rows, name) == early(plain_rows, name)
    assert plain_seen[4]["disruptions"] == []
    assert [disruption["start"] for disruption in seen[4]["disruptions"]] == [8]
    # Buys arrive 2 periods after they are placed. Without notice, the buys of
    # periods 1 and 3 arrive whole before the outage: 2 * 50 = 100. With notice,
    # the buys of periods 4 and 5 also arrive whole, and the buys of periods 6 and
    # 7 arrive in periods 8 and 9 of the outage, each 50 * (1 - 0.8000) = 10.
    assert plain_arrived == 100
    assert arrived == 4 * 50 + 2 * 10
