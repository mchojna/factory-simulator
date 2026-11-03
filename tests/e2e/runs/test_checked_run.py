from typing import Any

import pytest
from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    post,
    produce,
    records,
    rows_of_run,
    ship,
    start_run,
    submit,
    tiny_scenario,
)

from factory_simulator.api.record.models.run import Interaction

HORIZON = 12


def decisions_of(period: int) -> list[dict[str, Any]]:
    return [
        ship(f"order-{period}-1", "4"),
        ship("order-99-1", "1"),
        produce("board", "10"),
        produce("monitor", "4"),
        buy("5000"),
        buy("40"),
    ]


def sorted_outcomes(outcomes: list[Any]) -> list[Any]:
    return sorted(
        outcomes, key=lambda outcome: int(outcome["decision_id"].split("-")[1])
    )


@pytest.mark.slow
def test_a_run_that_drops_the_rejected_decisions_of_its_checks():
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    with api_client() as client:
        checked_run = start_run(client, scenario=scenario, seed=2)
        direct_run = start_run(client, scenario=scenario, seed=2)
        full_run = start_run(client, scenario=scenario, seed=2)
        checks: list[Any] = []
        rejected: list[tuple[str, str]] = []
        for period in range(1, HORIZON + 1):
            decisions = decisions_of(period)
            status, checked = post(
                client,
                f"/runs/{checked_run['id']}/checks",
                {"period": period, "decisions": decisions},
            )
            assert status == 200, checked
            checks.append(sorted_outcomes(checked["outcomes"]))
            accepted = [
                decision
                for decision, outcome in zip(
                    decisions, sorted_outcomes(checked["outcomes"]), strict=True
                )
                if outcome["accepted"]
            ]
            rejected += [
                (outcome["decision_id"], outcome["reason"])
                for outcome in sorted_outcomes(checked["outcomes"])
                if not outcome["accepted"]
            ]
            for run in (checked_run, direct_run):
                status, answer = submit(client, run["id"], period, accepted)
                assert status == 200, answer
            status, answer = submit(client, full_run["id"], period, decisions)
            assert status == 200, answer
        _, full_periods = get(client, f"/runs/{full_run['id']}/periods")
        _, full_result = get(client, f"/runs/{full_run['id']}/result")
        checked_rows = rows_of_run(client, checked_run["id"])
        direct_rows = rows_of_run(client, direct_run["id"])
        interactions = records(client, Interaction, run_id=checked_run["id"])

    # Each period the ship of order-99-1 names no order and the buy of 5000 is above
    # the max quantity of 1000; every other decision is accepted.
    assert rejected == [
        (f"{period}-{position}", reason)
        for period in range(1, HORIZON + 1)
        for position, reason in ((2, "unknown_order"), (5, "over_max_quantity"))
    ]
    assert checks == [
        sorted_outcomes(
            [
                outcome
                for step in period["steps"]
                for outcome in step.get("outcomes", [])
            ]
        )
        for period in full_periods["periods"]
    ]
    assert checked_rows == direct_rows
    assert_run_balances(full_periods, full_result)
    assert [row["kind"] for row in interactions] == ["check"] * HORIZON
    assert [row["period"] for row in interactions] == list(range(1, HORIZON + 1))
