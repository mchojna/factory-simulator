from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10
AHEAD = 2
CANCELLED_START = 5
BOARDS = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "5"}


def planned_decisions() -> dict[int, list[dict[str, Any]]]:
    decisions: dict[int, list[dict[str, Any]]] = {
        period: [BOARDS | {"start": period + AHEAD}]
        for period in range(1, HORIZON - AHEAD + 1)
    }
    decided = CANCELLED_START - AHEAD
    decisions[decided + 1].append({"kind": "cancel", "order": f"make-{decided}-1"})
    return decisions


def direct_decisions() -> dict[int, list[dict[str, Any]]]:
    return {
        period: [BOARDS]
        for period in range(1 + AHEAD, HORIZON + 1)
        if period != CANCELLED_START
    }


def periods_of(decisions: dict[int, list[dict[str, Any]]]) -> list[Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    assert_run_balances(periods, result)
    return [
        (
            period["steps"][-1]["state"]["stock"],
            period["steps"][-1]["state"]["cash"],
            period["steps"][-1]["measures"]["total"]["profit_so_far"],
        )
        for period in periods["periods"]
    ]


def test_a_run_of_plans_equals_a_run_of_the_same_produces_in_their_start_periods():
    assert periods_of(planned_decisions()) == periods_of(direct_decisions())
