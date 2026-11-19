from decimal import Decimal, localcontext
from typing import Any

import pytest
from factories import (
    REASONS,
    Client,
    api_client,
    draw_world_of_bodies,
    engine_of,
    example_count,
    get,
    observed_decision_lists,
    plain_tiny_manifest,
    plain_tiny_scenario,
    post,
    records,
    rows_of_run,
    run_to_the_end,
    seeds,
    server_of,
    ship,
    small_factories,
    start_run,
    statements_of,
    submit,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.run import Interaction, Period
from factory_simulator.api.services.runs import runs

SHIP = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
MAKE_MONITORS = {
    "kind": "produce",
    "line": "line-1",
    "item": "monitor",
    "quantity": "4",
}
MAKE_BOARDS = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "20"}
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "50"}
FactoryBodies = tuple[dict[str, Any], dict[str, Any]]


def check(
    client: Client, run_id: str, period: int, decisions: list[Any]
) -> tuple[int, Any]:
    return post(
        client, f"/runs/{run_id}/checks", {"period": period, "decisions": decisions}
    )


def stocked_run(client: Client, monitors: str, *orders: str) -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["monitor"] = monitors
    scenario["start"]["customer_orders"] = [
        {
            "customer": "distributor",
            "product": "monitor",
            "quantity": quantity,
            "due": 2,
        }
        for quantity in orders
    ]
    return start_run(client, scenario=scenario)


def run_to_the_end_of(
    client: Client, run_id: str, decisions: dict[int, list[Any]], last: int
) -> None:
    for period in range(1, last + 1):
        status, answer = submit(client, run_id, period, decisions.get(period, []))
        assert status == 200, answer


def test_a_check_of_the_full_period_example_accepts_all_and_changes_nothing():
    with api_client() as client:
        run = start_run(client)
        _, before = get(client, f"/runs/{run['id']}/observation")
        status, checked = check(
            client, run["id"], 1, [SHIP, MAKE_MONITORS, MAKE_BOARDS, BUY]
        )
        _, after = get(client, f"/runs/{run['id']}/observation")

    assert status == 200
    assert [
        (outcome["accepted"], outcome["reference"]) for outcome in checked["outcomes"]
    ] == [
        (True, "ship-1-1"),
        (True, "make-1-2"),
        (True, "make-1-3"),
        (True, "buy-1-4"),
    ]
    assert after == before
    assert (after["cash"], after["stock"]["main"]) == (
        Decimal(1000),
        {"chip": Decimal(100), "board": Decimal(10), "monitor": Decimal(5)},
    )
    assert after["lines"]["line-1"]["condition"] == 1


def test_a_check_gives_the_reason_of_a_rejection():
    with api_client() as client:
        run = stocked_run(client, "40.000", "50.000")
        order_ship = {"kind": "ship", "order": "order-0-1"}
        _, too_many = check(client, run["id"], 1, [order_ship | {"quantity": "50.000"}])
        _, enough = check(client, run["id"], 1, [order_ship | {"quantity": "40.000"}])

    [rejected] = too_many["outcomes"]
    assert (rejected["reason"], rejected["asked"], rejected["available"]) == (
        "not_enough_stock",
        Decimal(50),
        Decimal(40),
    )
    assert [outcome["accepted"] for outcome in enough["outcomes"]] == [True]


# 600 chips at 2.0000 cost 1200; cash 1000, no credit and nothing owed leave 1000.
def test_a_check_refuses_a_buy_beyond_the_credit_limit_and_leaves_the_run():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "2.0000"
    with api_client() as client:
        run = start_run(client, manifest)
        _, before = get(client, f"/runs/{run['id']}/observation")
        _, checked = check(client, run["id"], 1, [BUY | {"quantity": "600"}])
        _, after = get(client, f"/runs/{run['id']}/observation")

    [rejected] = checked["outcomes"]
    assert (rejected["reason"], rejected["asked"], rejected["available"]) == (
        "over_credit_limit",
        Decimal("1200.0000"),
        Decimal("1000.0000"),
    )
    assert after == before


# Cash 1, credit limit 0, a stopped line whose full repair costs 2, chips at 1.0000. A
# repair of 1 is never checked for cash and leaves -1; a buy of 1 chip leaves 0. Their
# midpoint repairs 0.5 for 1, which leaves 0, and its buy of 0.5 chip for 0.5000 then
# goes below the limit, so the decisions that pass the check form no convex set.
def test_a_repair_and_a_buy_each_pass_the_credit_check_but_their_midpoint_does_not():
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "1.0000"
    manifest["lines"]["line-1"]["repair_cost"] = "2.0000"
    scenario = plain_tiny_scenario()
    scenario["start"] = {"cash": "1", "stock": {}, "condition": {"line-1": "0"}}
    repair = {"kind": "repair", "line": "line-1"}
    chip_buy = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        _, repair_only = check(client, run["id"], 1, [repair | {"amount": "1"}])
        _, buy_only = check(client, run["id"], 1, [chip_buy | {"quantity": "1"}])
        _, midpoint = check(
            client,
            run["id"],
            1,
            [repair | {"amount": "0.5"}, chip_buy | {"quantity": "0.5"}],
        )

    assert [outcome["accepted"] for outcome in repair_only["outcomes"]] == [True]
    assert [outcome["accepted"] for outcome in buy_only["outcomes"]] == [True]
    repaired, refused = midpoint["outcomes"]
    assert repaired["accepted"]
    assert (refused["reason"], refused["asked"], refused["available"]) == (
        "over_credit_limit",
        Decimal("0.5000"),
        Decimal("0.0000"),
    )


def test_a_check_counts_the_decisions_accepted_before():
    with api_client() as client:
        run = stocked_run(client, "40.000", "30.000", "30.000")
        ships = [ship(f"order-0-{number}", "30.000") for number in (1, 2)]
        _, checked = check(client, run["id"], 1, ships)

    first, second = checked["outcomes"]
    assert first["accepted"]
    assert (second["reason"], second["asked"], second["available"]) == (
        "not_enough_stock",
        Decimal(30),
        Decimal(10),
    )


def test_a_check_lists_the_plans_of_the_period_first():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(wear_per_period="0.0000", wear_per_hour="0.0000")
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["board"] = "100"
    plan = {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "16"}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end_of(client, run["id"], {3: [plan | {"start": 5}]}, 4)
        production = plan | {"quantity": "8.000"}
        _, checked = check(client, run["id"], 5, [production])

    planned, rejected = checked["outcomes"]
    assert (planned["decision_id"], planned["accepted"]) == ("3-1", True)
    assert (rejected["reason"], rejected["asked"], rejected["available"]) == (
        "not_enough_hours",
        Decimal(4),
        Decimal(2),
    )


def test_every_check_is_kept_in_interactions_and_no_period_is_written():
    with api_client() as client:
        run = start_run(client)
        check(client, run["id"], 1, [SHIP])
        check(client, run["id"], 1, [BUY])
        submit(client, run["id"], 1, [])
        rows = records(client, Interaction, run_id=run["id"])
        periods = records(client, Period, run_id=run["id"])

    assert [(row["position"], row["period"], row["kind"]) for row in rows] == [
        (1, 1, "check"),
        (2, 1, "check"),
    ]
    assert [row["submission"]["decisions"][0]["kind"] for row in rows] == [
        "ship",
        "buy",
    ]
    assert [row["submission"]["period"] for row in rows] == [1, 1]
    assert all(row["outcomes"][0]["accepted"] for row in rows)
    assert all(row["refusal"] is None for row in rows)
    assert len(periods) == 1


def test_a_check_gives_the_outcomes_the_submission_records():
    decisions = [SHIP, MAKE_MONITORS, BUY | {"quantity": "5000"}]
    with api_client() as client:
        run = start_run(client)
        _, checked = check(client, run["id"], 1, decisions)
        status, _ = submit(client, run["id"], 1, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert status == 200
    steps = {step["step"]: step for step in periods["periods"][0]["steps"]}
    assert checked["outcomes"] == steps["execute_decisions"]["outcomes"]
    assert any(not outcome["accepted"] for outcome in checked["outcomes"])


def test_a_refused_check_is_kept_and_leaves_the_run():
    with api_client() as client:
        run = start_run(client)
        other_period = check(client, run["id"], 2, [])
        four_places = check(client, run["id"], 1, [SHIP | {"quantity": "1.0001"}])
        not_json = client.post(f"/api/v1/runs/{run['id']}/checks", content=b"not json")
        rows = records(client, Interaction, run_id=run["id"])
        _, after = get(client, f"/runs/{run['id']}")

    assert other_period == (409, {"detail": "period: is 2, the run is in period 1"})
    assert four_places[0] == 422
    assert four_places[1]["detail"].startswith("decisions.0.quantity: ")
    assert not_json.status_code == 422
    assert not_json.json()["detail"].startswith("body: ")
    assert [(row["kind"], row["outcomes"]) for row in rows] == [("check", None)] * 3
    assert all(row["refusal"] for row in rows)
    assert rows[2]["submission"] == "not json"
    assert after["period"] == 1


def test_a_check_on_an_unknown_or_finished_run_writes_no_interaction():
    with api_client() as client:
        unknown = check(client, "abc", 1, [])
        broken_unknown = client.post("/api/v1/runs/abc/checks", content=b"{not json")
        run = start_run(client)
        run_to_the_end(client, run)
        finished = check(client, run["id"], 5, [])
        broken_finished = client.post(
            f"/api/v1/runs/{run['id']}/checks", content=b"{not json"
        )
        rows = records(client, Interaction)

    assert unknown == (404, {"detail": "run_id: unknown run abc"})
    assert finished == (409, {"detail": "run: the run is finished"})
    assert (broken_unknown.status_code, broken_finished.status_code) == (404, 409)
    assert rows == []


def test_a_check_in_the_thread_pool_equals_one_in_a_narrow_decimal_context():
    decisions = [SHIP, MAKE_MONITORS, MAKE_BOARDS, BUY]
    body = write_json({"period": 1, "decisions": decisions})
    with api_client() as client:
        run = start_run(client)
        _, over_http = check(client, run["id"], 1, decisions)
        with Session(engine_of(client)) as session, localcontext() as context:
            context.prec = 28
            direct = runs.create_check(server_of(client), session, run["id"], body)

    assert write_json(direct) == write_json(over_http)


# Each period 0 to 2 checks before the submission: the first, when there is one, of
# the decisions submitted, the others of other drawn decisions. With no checks the two
# runs are two runs of the same inputs.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_checks_answer_the_outcomes_of_the_submission_and_leave_every_row_of_the_run(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed=seed)
    checked: dict[int, Any] = {}
    reasons: set[str] = set()
    with api_client() as client:
        plain_run = start_run(client, *factory, seed)
        checked_run = start_run(client, *factory, seed)
        _, observation = get(client, f"/runs/{plain_run['id']}/observation")
        period = 1
        while not observation.get("finished", False):
            decisions = data.draw(observed_decision_lists(world, observation))
            for position in range(data.draw(st.integers(0, 2))):
                tried = (
                    decisions
                    if position == 0
                    else data.draw(observed_decision_lists(world, observation))
                )
                _, answer = check(client, checked_run["id"], period, tried)
                reasons |= {outcome.get("reason") for outcome in answer["outcomes"]}
                if position == 0:
                    checked[period] = answer["outcomes"]
            submit(client, checked_run["id"], period, decisions)
            _, observation = submit(client, plain_run["id"], period, decisions)
            period += 1
        _, periods = get(client, f"/runs/{checked_run['id']}/periods")
        plain_rows = rows_of_run(client, plain_run["id"])
        checked_rows = rows_of_run(client, checked_run["id"])

    for period_entry in periods["periods"]:
        steps = {step["step"]: step for step in period_entry["steps"]}
        outcomes = steps["execute_decisions"]["outcomes"]
        assert checked.get(period_entry["period"], outcomes) == outcomes
        reasons |= {outcome.get("reason") for outcome in outcomes}
    assert reasons - {None} <= REASONS
    assert checked_rows == plain_rows


def test_the_statements_of_a_check_do_not_grow_with_the_earlier_interactions():
    body: dict[str, Any] = {"period": 1, "decisions": []}
    with api_client() as client:
        run = start_run(client)
        path = f"/runs/{run['id']}/checks"
        first = statements_of(client, lambda: post(client, path, body))
        for _ in range(20):
            post(client, path, body)
        later = statements_of(client, lambda: post(client, path, body))
        rows = records(client, Interaction, run_id=run["id"])

    reads = [text for text in later if "interactions" in text and "INSERT" not in text]
    assert len(later) == len(first)
    assert reads == []
    assert sorted(row["position"] for row in rows) == list(range(1, 23))
