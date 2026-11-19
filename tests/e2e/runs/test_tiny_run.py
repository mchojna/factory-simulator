from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)


def test_tiny_factory_runs_5_periods_and_writes_its_result():
    with api_client() as client:
        run = start_run(client, seed=3)
        run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert result["seed"] == 3
    assert result["periods"] == 5
    assert result["cash_at_start"] == Decimal("1000")
    assert result["cash_at_end"] == Decimal("766.2202")
    assert result["terms"] == {
        "revenue": 0,
        "material_payment": 0,
        "production_cost": 0,
        "transport_cost": 0,
        "storage_cost": 4,
        "repair_cost": 0,
        "cancellation_fee": 0,
        "overtime_cost": 0,
        "changeover_cost": 0,
        "transfer_cost": 0,
        "interest_paid": 0,
        "interest_earned": Decimal("2.2202"),
        "late_penalty": 32,
        "lost_sale_penalty": 200,
        "salvage": 25,
    }
    assert result["profit"] == Decimal("-208.7798")
    assert_run_balances(periods, result)


def test_tiny_factory_ships_every_new_order_in_full_and_pays_no_penalty():
    manifest = tiny_manifest()
    for rate in ("credit_interest", "debit_interest", "overdraft_interest"):
        manifest["cash"][rate] = "0.0000"
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["monitor"] = "20"

    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=3)
        answer: Any = run
        while not answer.get("finished", False):
            _, observation = get(client, f"/runs/{run['id']}/observation")
            ships = [
                {"kind": "ship", "order": order["id"], "quantity": order["quantity"]}
                for order in observation["customer_orders"]
            ]
            status, answer = submit(client, run["id"], observation["period"], ships)
            assert status == 200, answer
        _, result = get(client, f"/runs/{run['id']}/result")

    terms = result["terms"]
    assert terms["revenue"] == 1000
    assert terms["transport_cost"] == 20
    assert terms["storage_cost"] == Decimal("5.5")
    assert terms["late_penalty"] == 0
    assert terms["lost_sale_penalty"] == 0
    assert terms["interest_earned"] == 0
    assert terms["salvage"] == 15
    assert result["profit"] == Decimal("989.5")


def test_tiny_factory_makes_boards_then_monitors_and_ships_them():
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"] = {"chip": "100", "board": "0", "monitor": "0"}
    produce = {"kind": "produce", "line": "line-1"}
    decisions = {
        1: [produce | {"item": "board", "quantity": "20"}],
        2: [produce | {"item": "monitor", "quantity": "9"}],
        3: [{"kind": "ship", "order": "order-3-1", "quantity": "4"}],
        4: [{"kind": "ship", "order": "order-4-1", "quantity": "4"}],
        5: [{"kind": "ship", "order": "order-5-1", "quantity": "1"}],
    }
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=3)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    steps = [step for period in periods["periods"] for step in period["steps"]]
    good: dict[str, Decimal] = {}
    for step in steps:
        for event in step.get("events", []):
            if event["kind"] == "production_finished":
                good[event["item"]] = (
                    good.get(event["item"], Decimal(0)) + event["good"]
                )
    accepted = [
        outcome["decision"]
        for step in steps
        for outcome in step.get("outcomes", [])
        if outcome["accepted"]
    ]
    recipes = {"board": {"chip": Decimal(2)}, "monitor": {"board": Decimal(2)}}
    out: dict[str, Decimal] = {}
    for decision in accepted:
        if decision["kind"] == "produce":
            for input_id, per_unit in recipes[decision["item"]].items():
                out[input_id] = out.get(input_id, Decimal(0)) + (
                    decision["quantity"] * per_unit
                )
        else:
            out["monitor"] = out.get("monitor", Decimal(0)) + decision["quantity"]
    start = {"chip": Decimal(100), "board": Decimal(0), "monitor": Decimal(0)}
    end = periods["periods"][-1]["steps"][-1]["state"]["stock"]["main"]
    ledger = [
        row["amount"] for period in periods["periods"] for row in period["ledger"]
    ]

    assert len(accepted) == 5
    assert good == {"board": Decimal(18), "monitor": Decimal(9)}
    for item_id, quantity in start.items():
        assert quantity + good.get(item_id, 0) == end[item_id] + out.get(item_id, 0)
    assert sum(ledger) == result["cash_at_end"] - result["cash_at_start"]


def test_tiny_factory_buys_chips_makes_monitors_and_ships_them_over_10_periods():
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["start"]["stock"]["main"] = {"chip": "0", "board": "0", "monitor": "0"}
    produce = {"kind": "produce", "line": "line-1"}
    buy = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
    decisions: dict[int, list[Any]] = {
        1: [buy | {"quantity": "100"}],
        3: [produce | {"item": "board", "quantity": "40"}],
        4: [produce | {"item": "monitor", "quantity": "18"}],
    }
    for period, quantity in [(5, "4"), (6, "4"), (7, "4"), (8, "4"), (9, "2")]:
        decisions[period] = [
            {"kind": "ship", "order": f"order-{period}-1", "quantity": quantity}
        ]
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=3)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    steps = [step for period in periods["periods"] for step in period["steps"]]
    events = [event for step in steps for event in step.get("events", [])]
    accepted = [
        outcome["decision"]
        for step in steps
        for outcome in step.get("outcomes", [])
        if outcome["accepted"]
    ]
    into: dict[str, Decimal] = {}
    for event in events:
        if event["kind"] == "delivery":
            into["chip"] = into.get("chip", Decimal(0)) + event["accepted"]
        if event["kind"] == "production_finished":
            into[event["item"]] = into.get(event["item"], Decimal(0)) + event["good"]
    recipes = {"board": {"chip": Decimal(2)}, "monitor": {"board": Decimal(2)}}
    out: dict[str, Decimal] = {}
    for decision in accepted:
        if decision["kind"] == "produce":
            for input_id, per_unit in recipes[decision["item"]].items():
                out[input_id] = out.get(input_id, Decimal(0)) + (
                    decision["quantity"] * per_unit
                )
        if decision["kind"] == "ship":
            out["monitor"] = out.get("monitor", Decimal(0)) + decision["quantity"]
    end = periods["periods"][-1]["steps"][-1]["state"]["stock"]["main"]
    delivery = next(event for event in events if event["kind"] == "delivery")
    ledger = [
        row["amount"] for period in periods["periods"] for row in period["ledger"]
    ]

    assert len(accepted) == 8
    for item_id in ("chip", "board", "monitor"):
        assert into.get(item_id, 0) == end[item_id] + out.get(item_id, 0)
    assert delivery["ordered"] == (
        delivery["accepted"]
        + (delivery["arrived"] - delivery["accepted"])
        + delivery["lost"]
    )
    assert sum(ledger) == result["cash_at_end"] - result["cash_at_start"]


def test_a_line_broken_in_period_3_recovers_by_repair_and_ships_from_period_5():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"] |= {
        "breakdown_chance": "0.2000",
        "breakdown_loss": "1.0000",
    }
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    produce = {"kind": "produce", "line": "line-1", "item": "monitor"}
    decisions: dict[int, list[Any]] = {
        1: [{"kind": "ship", "order": "order-1-1", "quantity": "4"}],
        2: [{"kind": "ship", "order": "order-2-1", "quantity": "1"}],
        3: [
            {"kind": "repair", "line": "line-1", "amount": "0.5000"},
            produce | {"quantity": "1"},
        ],
        4: [produce | {"quantity": "4"}],
        5: [{"kind": "ship", "order": "order-5-1", "quantity": "4"}],
    }
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=16)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    periods_by_number = {period["period"]: period for period in periods["periods"]}

    def steps(period: int) -> dict[str, Any]:
        return {step["step"]: step for step in periods_by_number[period]["steps"]}

    breakdowns = [
        (period, event["condition"])
        for period in periods_by_number
        for event in steps(period)["apply_events"]["events"]
        if event["kind"] == "breakdown"
    ]
    accepted = {
        period: [
            outcome["accepted"]
            for outcome in steps(period)["execute_decisions"]["outcomes"]
        ]
        for period in periods_by_number
    }
    ledger = [
        row["amount"] for period in periods["periods"] for row in period["ledger"]
    ]

    assert breakdowns == [(3, 0)]
    assert accepted[3] == [True, False]
    assert accepted[4] == [True]
    assert accepted[5] == [True]
    assert sum(ledger) == result["cash_at_end"] - result["cash_at_start"]


def test_one_disruption_of_every_kind_shows_its_effect_in_its_window():
    def one(kind: str, target: str, start: int, **effect: object) -> dict[str, Any]:
        disruption: dict[str, Any] = {"kind": kind, "target": [target], "start": start}
        if kind != "line_breakdown":
            disruption["duration"] = 1
        return disruption | effect

    scenario = tiny_scenario()
    scenario["horizon"] = 8
    scenario["disruptions"] = [
        one("capacity_cut", "line-1", 1, strength="0.5000"),
        one("material_shortage", "chip", 2, strength="0.5000"),
        one("demand_shock", "monitor", 2, factor="2.0000"),
        one("supplier_outage", "chip-maker", 3, strength="0.5000"),
        one("price_change", "chip", 4, factor="1.2000"),
        one("quality_drop", "chip-maker", 5, strength="0.5000"),
        one("transport_delay", "chip-maker", 6, delay=1),
        one("line_breakdown", "line-1", 6, loss="0.5000"),
    ]
    buy = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
    decisions: dict[int, list[Any]] = {
        1: [
            {"kind": "produce", "line": "line-1", "item": "board", "quantity": "60"},
            buy | {"quantity": "100"},
        ],
        2: [buy | {"quantity": "600"}],
        3: [buy | {"quantity": "100"}],
        4: [buy | {"quantity": "100"}],
    }
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=3)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    periods_by_number = {period["period"]: period for period in periods["periods"]}

    def events(period: int, kind: str) -> list[dict[str, Any]]:
        return [
            event
            for step in periods_by_number[period]["steps"]
            for event in step.get("events", [])
            if event["kind"] == kind
        ]

    def reasons(period: int) -> list[str]:
        step = {step["step"]: step for step in periods_by_number[period]["steps"]}
        return [
            outcome.get("reason", "")
            for outcome in step["execute_decisions"]["outcomes"]
        ]

    deliveries = {
        period: [(event["reference"], event["arrived"], event["accepted"])]
        for period in periods_by_number
        if events(period, "delivery")
        for event in events(period, "delivery")
    }
    state_4 = periods_by_number[4]["steps"][-1]["state"]
    ledger = [
        row["amount"] for period in periods["periods"] for row in period["ledger"]
    ]

    assert reasons(1) == ["not_enough_hours", ""]
    assert reasons(2) == ["over_max_quantity"]
    assert [event["quantity"] for event in events(2, "customer_order")] == [8]
    assert deliveries == {
        3: [("buy-1-2", 50, 50)],
        5: [("buy-3-1", 100, 50)],
        7: [("buy-4-1", 100, 100)],
    }
    assert [order["unit_price"] for order in state_4["supplier_orders"]] == [
        Decimal("0.5"),
        Decimal("0.6"),
    ]
    assert [event["reference"] for event in events(6, "breakdown")] == ["disruption-8"]
    assert sum(ledger) == result["cash_at_end"] - result["cash_at_start"]


def test_new_orders_follow_a_trend_and_a_season():
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    scenario["demand_shapes"] = [
        {"kind": "trend", "target": "all", "rate": "0.1000"},
        {
            "kind": "season",
            "target": {"product": "monitor"},
            "factors": ["1.0000", "2.0000"],
            "period_length": 3,
        },
    ]
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=3)
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    ordered = [
        event["quantity"]
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "customer_order"
    ]
    # 4 * 1.1 ** (t - 1), times 2 from period 4, rounded half to even to 3 places.
    assert ordered == [
        Decimal("4"),
        Decimal("4.4"),
        Decimal("4.84"),
        Decimal("10.648"),
        Decimal("11.713"),
        Decimal("12.884"),
    ]
    assert result["periods"] == 6
