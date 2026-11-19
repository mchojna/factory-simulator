import copy
from dataclasses import asdict, replace
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

import pytest
from factories import (
    FactoryBodies,
    RunStep,
    acting_factor,
    buy,
    buy_lists,
    centre_world,
    closed_period,
    count_reached,
    draw_world_of_bodies,
    drawn_run,
    drawn_runs,
    example_count,
    example_scenario,
    first_period,
    linear_factories,
    outcome_fields,
    outcome_numbers,
    plain_tiny_manifest,
    seeds,
    small_factories,
    spare_world,
    started,
    starting_chips_scenario,
    submission,
    supplier_orders_of,
    tiered_chip_world,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.engine import (
    Disruption,
    State,
    SupplierOrder,
    World,
    advance_period,
    build_state,
    start_period,
)
from factory_simulator.engine.steps.execution import execute_decisions

PASSIVE_KIT = "emea-electronic-parts/passive-kit"


def chip_terms(manifest: dict[str, Any], **terms: str) -> dict[str, Any]:
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(terms)
    return manifest


def events_of(state: State, kind: str) -> list[dict[str, Any]]:
    return [dict(event) for event in state.period_events if event["kind"] == kind]


def outcomes_of(world: World, *decisions: dict[str, Any]) -> list[dict[str, Any]]:
    closed = first_period(world, list(decisions))
    return [outcome_fields(outcome) for outcome in closed.outcomes]


# The tiny factory with chips at 10.0000 and a credit limit of 500.0000.
def credit_manifest() -> dict[str, Any]:
    manifest = chip_terms(tiny_manifest(), price="10.0000")
    manifest["cash"]["credit_limit"] = "500.0000"
    return manifest


# The outcomes of the decisions of period 1 executed from a cash and open orders.
def outcomes_at_cash(
    manifest: dict[str, Any],
    cash: str,
    decisions: list[dict[str, Any]],
    supplier_orders: tuple[SupplierOrder, ...] = (),
) -> list[dict[str, Any]]:
    world = draw_world_of_bodies(manifest, tiny_scenario())
    state = replace(
        start_period(build_state(world), world),
        cash=Decimal(cash),
        supplier_orders=supplier_orders,
    )
    executed = execute_decisions(state, world, submission(1, decisions))
    return [
        {
            key: value
            for key, value in asdict(outcome).items()
            if value is not None and key not in ("decision", "decision_id")
        }
        for outcome in executed.outcomes
    ]


def open_chip_order(quantity: str, unit_price: str) -> SupplierOrder:
    return SupplierOrder(
        id="buy-0-1",
        supplier="chip-maker",
        material="chip",
        warehouse="main",
        quantity=Decimal(quantity),
        open_quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        express=False,
        placed=0,
        arrival=3,
    )


# The example factory with the passive kit priced every period from 2.2000 to 2.6000,
# delivered whole, and its drawn prices of periods 1, 3 and 4 set by hand.
def passive_kit_priced_every_period(**scenario_keys: object) -> World:
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    entry = manifest["suppliers"]["emea-electronic-parts"]["catalogue"]["passive-kit"]
    entry |= {
        "price": {"min": "2.2000", "max": "2.6000", "drawn": "period"},
        "punctuality": "1.0000",
        "completeness": "1.0000",
        "acceptance": "1.0000",
    }
    world = draw_world_of_bodies(manifest, example_scenario() | scenario_keys)
    kit_prices = list(world.prices[PASSIVE_KIT])
    kit_prices[0:4] = [
        Decimal("2.4000"),
        kit_prices[1],
        Decimal("2.3000"),
        Decimal("2.5600"),
    ]
    return replace(world, prices={PASSIVE_KIT: tuple(kit_prices)})


def passive_kit(quantity: str) -> dict[str, Any]:
    return buy(quantity, "passive-kit", "emea-electronic-parts") | {
        "warehouse": "main-plant"
    }


def expected_unit_price(world: World, order: SupplierOrder) -> Decimal:
    path = f"suppliers.{order.supplier}.catalogue.{order.material}"
    pair = f"{order.supplier}/{order.material}"
    if order.tier is not None:
        price = world.parameters[f"{path}.discounts.{order.tier}.price"]
    elif pair in world.prices:
        price = world.prices[pair][order.placed - 1]
    else:
        price = world.parameters[f"{path}.price"]
    changed = price * price_change_factor(world, order.material, order.placed)
    unit_price = changed.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    if order.express:
        unit_price += world.parameters[f"{path}.express_cost"]
    return unit_price


# The product of the factors of the price changes acting on a material in a period.
def price_change_factor(world: World, material: str, period: int) -> Decimal:
    product = Decimal(1)
    for disruption in world.disruptions:
        acts = disruption.start <= period < disruption.start + disruption.duration
        changes_material = material in materials_of_target(world, disruption)
        if disruption.kind == "price_change" and acts and changes_material:
            product *= disruption.effect
    return product


def materials_of_target(world: World, disruption: Disruption) -> set[str]:
    if disruption.group is not None:
        return set(world.factory.groups[disruption.group[1]].members)
    if disruption.target is not None:
        return set(disruption.target)
    return set(world.factory.materials)


# A factory with every written catalogue price drawn every period, a fixed price p
# becoming a range from p to p + 1, and a start cash that no buy reaches.
def priced_every_period(factory: FactoryBodies) -> FactoryBodies:
    manifest, scenario = copy.deepcopy(factory)
    for supplier in manifest["suppliers"].values():
        for entry in supplier["catalogue"].values():
            price = entry.get("price")
            if isinstance(price, dict):
                price["drawn"] = "period"
            elif price is not None:
                high = str(Decimal(price) + 1)
                entry["price"] = {"min": price, "max": high, "drawn": "period"}
    scenario.setdefault("start", {})["cash"] = "1000000"
    return manifest, scenario


def prices(state: State) -> dict[str, Decimal]:
    return {order.id: order.unit_price for order in state.supplier_orders}


def paid(state: State) -> Decimal:
    rows = [row.amount for row in state.ledger if row.kind == "material_payment"]
    return -sum(rows, Decimal(0))


def tiers(state: State) -> dict[str, Decimal | None]:
    return {order.id: order.tier for order in state.supplier_orders}


def price_change(factor: str) -> dict[str, Any]:
    return {
        "kind": "price_change",
        "target": ["chip"],
        "start": 1,
        "duration": 1,
        "factor": factor,
    }


def express_world(
    disruptions: list[dict[str, Any]] | None = None, **terms: object
) -> World:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        {
            "price": "5.0000",
            "lead_time": 4,
            "express_lead_time": 1,
            "express_cost": "1.5000",
        }
        | terms
    )
    scenario = tiny_scenario()
    scenario["horizon"] = 8
    scenario["disruptions"] = disruptions or []
    return draw_world_of_bodies(manifest, scenario)


def arrivals(world: World, decisions: dict[int, list[dict[str, Any]]]) -> list[Any]:
    found: list[Any] = []
    for period in range(1, 9):
        for event in started(world, period, decisions).period_events:
            if event["kind"] == "delivery":
                found.append((period, event["reference"], event["arrived"]))
    return found


def placed_orders(
    world: World, decisions: dict[int, list[dict[str, Any]]]
) -> tuple[SupplierOrder, ...]:
    return closed_period(world, 2, decisions).supplier_orders


# Whether a run places a buy at the price of a discount tier.
def places_a_buy_with_a_tier(run: tuple[World, list[RunStep]]) -> bool:
    orders = supplier_orders_of(*run).values()
    return any(order.tier is not None for order in orders)


def test_a_delivery_arrives_incomplete_and_is_paid_for_what_passes_inspection():
    manifest = chip_terms(
        tiny_manifest(), lead_time="4", completeness="0.9000", acceptance="0.9800"
    )
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = started(world, 5, {1: [buy("100")]})

    assert events_of(state, "delivery") == [
        {
            "kind": "delivery",
            "step": "receive_deliveries",
            "reference": "buy-1-1",
            "ordered": Decimal("100.000"),
            "arrived": Decimal("90.000"),
            "accepted": Decimal("88.200"),
            "lost": Decimal("10.000"),
            "payment": Decimal("44.1000000"),
            "backfill": False,
        }
    ]
    assert [
        (row.kind, row.amount, row.reference)
        for row in state.ledger
        if row.step == "receive_deliveries"
    ] == [("material_payment", Decimal("-44.1"), "buy-1-1")]
    assert state.supplier_orders == ()


def test_a_delivery_rounds_arrived_and_accepted_to_3_places():
    manifest = chip_terms(
        tiny_manifest(),
        lead_time="1",
        completeness="0.9537",
        acceptance="0.9812",
        price="0.5123",
    )
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = started(world, 2, {1: [buy("100.001")]})

    delivery = events_of(state, "delivery")[0]
    assert (delivery["arrived"], delivery["accepted"], delivery["lost"]) == (
        Decimal("95.371"),
        Decimal("93.578"),
        Decimal("4.630"),
    )
    assert delivery["payment"] == Decimal("47.9400094")
    assert delivery["arrived"] - delivery["accepted"] == Decimal("1.793")


def test_a_delivery_rounds_a_tie_of_arrived_half_to_even():
    manifest = chip_terms(tiny_manifest(), lead_time="1", completeness="0.1235")
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = started(world, 2, {1: [buy("3")]})

    delivery = events_of(state, "delivery")[0]
    assert (delivery["arrived"], delivery["accepted"]) == (
        Decimal("0.370"),
        Decimal("0.370"),
    )


def test_a_delivery_rounds_a_tie_of_accepted_half_to_even():
    manifest = chip_terms(tiny_manifest(), lead_time="1", acceptance="0.0125")
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = started(world, 2, {1: [buy("1")]})

    delivery = events_of(state, "delivery")[0]
    assert (delivery["arrived"], delivery["accepted"]) == (
        Decimal("1.000"),
        Decimal("0.012"),
    )


def test_a_delivery_with_nothing_arrived_has_its_event_and_no_ledger_row():
    manifest = chip_terms(tiny_manifest(), lead_time="1", completeness="0.0000")
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = started(world, 2, {1: [buy("50")]})

    assert events_of(state, "delivery")[0]["arrived"] == 0
    assert [row for row in state.ledger if row.step == "receive_deliveries"] == []


def test_a_late_order_arrives_lead_time_plus_delay_periods_after_placing():
    manifest = chip_terms(
        tiny_manifest(), lead_time="2", delay="1", punctuality="0.0000"
    )
    world = draw_world_of_bodies(manifest, tiny_scenario())

    arrival_periods = [
        period
        for period in range(2, 6)
        if events_of(started(world, period, {1: [buy("50")]}), "delivery")
    ]

    assert arrival_periods == [4]


def test_an_order_arriving_after_the_horizon_never_arrives_and_is_never_paid():
    manifest = chip_terms(tiny_manifest(), lead_time="5")
    world = draw_world_of_bodies(manifest, tiny_scenario())
    state = started(world, 5, {1: [buy("50")]})

    closed = advance_period(state, world, submission(5, []))

    assert closed.finished
    assert [order.id for order in closed.supplier_orders] == ["buy-1-1"]
    assert all(row.kind != "material_payment" for row in closed.ledger)
    assert events_of(closed, "delivery") == []


def test_buys_over_the_max_quantity_in_one_period_are_rejected_with_their_numbers():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())

    outcomes = outcomes_of(world, buy("600"), buy("500"))

    assert outcomes[1] == {
        "decision_id": "1-2",
        "accepted": False,
        "reason": "over_max_quantity",
        "asked": Decimal("500.000"),
        "available": Decimal("400.000"),
    }


def test_a_buy_from_an_unknown_supplier_or_not_in_its_catalogue_is_rejected():
    manifest = tiny_manifest()
    manifest["materials"]["glass"] = dict(manifest["materials"]["chip"])
    glass_maker = {
        "catalogue": {"glass": manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]}
    }
    manifest["suppliers"]["glass-maker"] = glass_maker
    world = draw_world_of_bodies(manifest, tiny_scenario())

    outcomes = outcomes_of(world, buy("1", supplier="north-chips"), buy("1", "glass"))

    assert outcomes == [
        {"decision_id": "1-1", "accepted": False, "reason": "unknown_supplier"},
        {"decision_id": "1-2", "accepted": False, "reason": "not_in_catalogue"},
    ]


def test_a_buy_over_the_space_of_the_warehouse_is_rejected_with_its_numbers():
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "2.000"
    world = draw_world_of_bodies(manifest, tiny_scenario())

    assert outcomes_of(world, buy("10")) == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "not_enough_space",
            "asked": Decimal("0.100"),
            "available": Decimal("0.050"),
        }
    ]


def test_a_buy_failing_two_checks_is_rejected_for_the_first_in_the_table():
    # The tiny start takes 1.000 + 0.200 + 0.750 = 1.950 of 2.450, so 0.500 is left;
    # 2000 chips take 20.000 and are above the max quantity of 1000.
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "2.450"
    world = draw_world_of_bodies(manifest, tiny_scenario())

    assert outcomes_of(world, buy("2000")) == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "over_max_quantity",
            "asked": Decimal("2000.000"),
            "available": Decimal("1000.000"),
        }
    ]


def test_identifiers_follow_the_position_in_the_submission():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}

    outcomes = outcomes_of(world, ship, buy("10"), buy("20"))

    assert [outcome["reference"] for outcome in outcomes] == [
        "ship-1-1",
        "buy-1-2",
        "buy-1-3",
    ]


def test_starting_supplier_orders_arrive_in_full_at_the_catalogue_price():
    scenario = tiny_scenario()
    scenario["start"]["supplier_orders"] = [
        {"supplier": "chip-maker", "material": "chip", "quantity": "100", "arrival": 3},
        {"supplier": "chip-maker", "material": "chip", "quantity": "5", "arrival": 4},
    ]
    world = draw_world_of_bodies(
        chip_terms(tiny_manifest(), completeness="0.5000"), scenario
    )

    before = start_period(build_state(world), world)
    arrived = started(world, 3, {})

    assert [order.id for order in before.supplier_orders] == ["buy-0-1", "buy-0-2"]
    assert events_of(arrived, "delivery") == [
        {
            "kind": "delivery",
            "step": "receive_deliveries",
            "reference": "buy-0-1",
            "ordered": Decimal("100.000"),
            "arrived": Decimal("100.000"),
            "accepted": Decimal("100.000"),
            "lost": Decimal("0.000"),
            "payment": Decimal("50"),
            "backfill": False,
        }
    ]


def test_a_buy_beyond_the_credit_limit_is_rejected_with_its_numbers():
    # 1000 - 0 - 160 * 10 = -600 is below -500; 1000 - 0 - 150 * 10 = -500 is not.
    rejected = outcomes_at_cash(credit_manifest(), "1000.0000", [buy("160")])
    accepted = outcomes_at_cash(credit_manifest(), "1000.0000", [buy("150")])

    assert rejected == [
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("1600.0000"),
            "available": Decimal("1500.0000"),
        }
    ]
    assert accepted == [{"accepted": True, "reference": "buy-1-1"}]


def test_a_rejection_over_the_credit_limit_gives_its_exact_numbers():
    # 0.001 * 0.1001 = 0.0001001 is above 0.0001 + 0 - 0.
    manifest = chip_terms(tiny_manifest(), price="0.1001")

    rejected = outcomes_at_cash(manifest, "0.0001", [buy("0.001")])

    assert rejected == [
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("0.0001001"),
            "available": Decimal("0.0001"),
        }
    ]


def test_a_rejection_over_the_credit_limit_gives_the_11_places_of_cash():
    # Storage of period 1 is 1.001 * 0.0001 * 1.0001 = 0.00010011001, the only cost, so
    # cash and the credit available in period 2 are -0.00010011001.
    manifest = chip_terms(plain_tiny_manifest(), price="1.0000")
    manifest["materials"]["chip"]["storage_cost"] = "0.0001"
    manifest["warehouses"]["main"]["storage_factor"] = "1.0001"
    pair = manifest["customers"]["distributor"]["products"]["monitor"]
    pair |= {"late_penalty": "0.0000", "lost_sale_penalty": "0.0000"}
    scenario = {
        "horizon": 2,
        "start": {"cash": "0", "stock": {"main": {"chip": "1.001"}}},
    }
    world = draw_world_of_bodies(manifest, scenario)

    period_2 = closed_period(world, 2, {2: [buy("1")]})

    assert period_2.outcomes[0].reason == "over_credit_limit"
    assert (period_2.outcomes[0].asked, period_2.outcomes[0].available) == (
        Decimal(1),
        Decimal("-0.00010011001"),
    )


def test_open_supplier_orders_count_against_the_credit_limit():
    # committed = 200 * 2 = 400, available = 1000 + 500 - 400 = 1100.
    orders = (open_chip_order("200", "2.0000"),)

    accepted = outcomes_at_cash(credit_manifest(), "1000.0000", [buy("110")], orders)
    rejected = outcomes_at_cash(credit_manifest(), "1000.0000", [buy("111")], orders)

    assert accepted == [{"accepted": True, "reference": "buy-1-1"}]
    assert rejected == [
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("1110.0000"),
            "available": Decimal("1100.0000"),
        }
    ]


def test_a_buy_accepted_earlier_in_the_period_counts_against_the_credit_limit():
    # After 100 * 10 = 1000, available is 1500 - 1000 = 500 against 60 * 10 = 600.
    outcomes = outcomes_at_cash(credit_manifest(), "1000.0000", [buy("100"), buy("60")])

    assert outcomes == [
        {"accepted": True, "reference": "buy-1-1"},
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("600.0000"),
            "available": Decimal("500.0000"),
        },
    ]


def test_an_express_buy_counts_its_express_cost_against_the_credit_limit():
    # The unit price is 10 + 2 = 12: 125 * 12 = 1500 fits 1500, 126 * 12 = 1512 not.
    manifest = chip_terms(
        credit_manifest(), express_lead_time="1", express_cost="2.0000"
    )
    express = {"express": True}

    accepted = outcomes_at_cash(manifest, "1000.0000", [buy("125") | express])
    rejected = outcomes_at_cash(manifest, "1000.0000", [buy("126") | express])

    assert accepted == [{"accepted": True, "reference": "buy-1-1"}]
    assert rejected == [
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("1512.0000"),
            "available": Decimal("1500.0000"),
        }
    ]


def test_a_buy_at_a_discount_counts_the_price_of_its_tier_against_the_credit_limit():
    # 160 * 9 = 1440 fits 1500; at the catalogue price 160 * 10 = 1600 would not.
    manifest = credit_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["discounts"] = [
        {"from": "100.000", "price": "9.0000"}
    ]

    outcomes = outcomes_at_cash(manifest, "1000.0000", [buy("160")])

    assert outcomes == [{"accepted": True, "reference": "buy-1-1"}]


def test_a_buy_below_the_credit_limit_has_a_negative_available():
    # available = -600 + 500 - 0 = -100.
    outcomes = outcomes_at_cash(credit_manifest(), "-600.0000", [buy("1")])

    assert outcomes == [
        {
            "accepted": False,
            "reason": "over_credit_limit",
            "asked": Decimal("10.0000"),
            "available": Decimal("-100.0000"),
        }
    ]


def test_a_ship_paid_at_once_raises_the_cash_a_later_buy_is_checked_against():
    # The ship of 4 at 125 brings 500 at once: available 1500 + 500 = 2000.
    manifest = credit_manifest()
    monitor = manifest["customers"]["distributor"]["products"]["monitor"]
    monitor |= {"price": "125.0000", "transport_cost": "0.0000"}
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}

    outcomes = outcomes_at_cash(manifest, "1000.0000", [buy("200"), ship])

    assert outcomes == [
        {"accepted": True, "reference": "ship-1-2"},
        {"accepted": True, "reference": "buy-1-1"},
    ]


def test_a_cancel_earlier_in_the_period_lowers_what_counts_against_the_limit():
    # The cancel of 100 of 200 at 2 lowers committed from 400 to 200, so available
    # is 1000 + 500 - 200 = 1300.
    orders = (open_chip_order("200", "2.0000"),)
    cancel = {"kind": "cancel", "order": "buy-0-1", "quantity": "100"}

    accepted = outcomes_at_cash(
        credit_manifest(), "1000.0000", [cancel, buy("130")], orders
    )
    rejected = outcomes_at_cash(
        credit_manifest(), "1000.0000", [cancel, buy("131")], orders
    )

    assert accepted[1] == {"accepted": True, "reference": "buy-1-2"}
    assert rejected[1] == {
        "accepted": False,
        "reason": "over_credit_limit",
        "asked": Decimal("1310.0000"),
        "available": Decimal("1300.0000"),
    }


def test_a_buy_short_of_space_and_of_credit_is_rejected_for_lack_of_space():
    manifest = credit_manifest()
    manifest["warehouses"]["main"]["capacity"] = "2.000"

    outcomes = outcomes_at_cash(manifest, "1000.0000", [buy("160")])

    assert outcomes[0]["reason"] == "not_enough_space"


def test_a_buy_pays_the_price_of_its_placing_period_whatever_its_arrival():
    world = passive_kit_priced_every_period()
    decisions = {3: [passive_kit("100")], 4: [passive_kit("100")]}

    # A lead time of 2 brings the orders of periods 3 and 4 in periods 5 and 6.
    payments = [
        (row.reference, row.amount)
        for period in (5, 6)
        for row in started(world, period, decisions).ledger
        if row.kind == "material_payment"
    ]

    assert payments == [
        ("buy-3-1", Decimal("-230.0000")),
        ("buy-4-1", Decimal("-256.0000")),
    ]


def test_a_price_change_multiplies_the_price_of_the_placing_period():
    change = {
        "kind": "price_change",
        "target": ["passive-kit"],
        "start": 3,
        "duration": 1,
        "factor": "1.2000",
    }
    world = passive_kit_priced_every_period(disruptions=[change])

    state = started(world, 4, {3: [passive_kit("100")]})

    assert [(order.id, order.unit_price) for order in state.supplier_orders] == [
        ("buy-3-1", Decimal("2.7600"))
    ]


def test_a_starting_supplier_order_takes_the_price_of_period_1():
    order = {
        "supplier": "emea-electronic-parts",
        "material": "passive-kit",
        "quantity": "100",
        "arrival": 3,
        "warehouse": "main-plant",
    }
    world = passive_kit_priced_every_period(
        start={"cash": "0", "supplier_orders": [order]}
    )

    state = start_period(build_state(world), world)

    assert [order.unit_price for order in state.supplier_orders] == [Decimal("2.4000")]


def test_a_buy_names_a_warehouse_that_exists_and_accepts_the_material():
    world = centre_world()

    state = first_period(
        world, [buy("10", warehouse="north-depot"), buy("10", warehouse="centre")]
    )

    assert outcome_numbers(state) == [
        (False, "unknown_warehouse", None, None),
        (False, "not_accepted", None, None),
    ]
    assert state.outcomes[1].item == "chip"


def test_a_buy_needs_space_in_its_own_warehouse():
    world = spare_world()

    state = first_period(
        world, [buy("200", warehouse="main"), buy("200", warehouse="spare")]
    )

    assert outcome_numbers(state) == [
        (False, "not_enough_space", Decimal("0.200"), Decimal("0.100")),
        (True, None, None, None),
    ]


def test_every_unit_of_an_order_pays_the_price_of_the_highest_tier_it_reaches():
    world = tiered_chip_world()

    one = closed_period(world, 1, {1: [buy("1200")]})
    two = closed_period(world, 1, {1: [buy("600"), buy("600")]})

    assert prices(one) == {"buy-1-1": Decimal("4.6000")}
    assert prices(two) == {"buy-1-1": Decimal("5.0000"), "buy-1-2": Decimal("5.0000")}
    assert paid(closed_period(world, 3, {1: [buy("1200")]})) == Decimal(5520)
    assert paid(closed_period(world, 3, {1: [buy("600"), buy("600")]})) == Decimal(6000)


def test_an_order_at_the_from_of_a_tier_pays_its_price_a_smaller_one_the_catalogue():
    world = tiered_chip_world()

    state = closed_period(world, 1, {1: [buy("5000"), buy("999.999")]})

    assert prices(state) == {
        "buy-1-1": Decimal("4.3000"),
        "buy-1-2": Decimal("5.0000"),
    }
    assert tiers(state) == {"buy-1-1": Decimal("5000.000"), "buy-1-2": None}
    assert paid(closed_period(world, 3, {1: [buy("5000")]})) == Decimal(21500)


def test_express_cost_and_price_changes_act_on_the_price_of_the_tier():
    express = tiered_chip_world(lead_time=3, express_lead_time=1, express_cost="1.5000")
    risen = tiered_chip_world(disruptions=[price_change("1.2000")])
    rounded = tiered_chip_world(disruptions=[price_change("1.0333")])

    assert prices(closed_period(express, 1, {1: [buy("1200", express=True)]})) == {
        "buy-1-1": Decimal("6.1000")
    }
    assert prices(closed_period(risen, 1, {1: [buy("1200")]})) == {
        "buy-1-1": Decimal("5.5200")
    }
    assert prices(closed_period(rounded, 1, {1: [buy("1200")]})) == {
        "buy-1-1": Decimal("4.7532")
    }
    assert paid(closed_period(rounded, 3, {1: [buy("1200")]})) == Decimal("5703.84")


def test_a_price_change_of_one_period_leaves_the_price_of_the_next_period():
    risen = tiered_chip_world(disruptions=[price_change("1.2000")])

    # The change acts in period 1 only: 4.6000 * 1.2 = 5.5200 then 4.6000 in period 2.
    assert prices(closed_period(risen, 1, {1: [buy("1200")]})) == {
        "buy-1-1": Decimal("5.5200")
    }
    assert prices(closed_period(risen, 2, {2: [buy("1200")]})) == {
        "buy-2-1": Decimal("4.6000")
    }


def test_a_tie_of_the_unit_price_rounds_half_to_even():
    world = tiered_chip_world(disruptions=[price_change("0.5000")], price="0.0373")

    assert prices(closed_period(world, 1, {1: [buy("10")]})) == {
        "buy-1-1": Decimal("0.0186")
    }


def test_a_starting_supplier_order_has_the_catalogue_price_and_no_tier():
    world = tiered_chip_world(starting_chips_scenario("1200"), min_quantity="1000.000")

    state = build_state(world)

    assert (prices(state), tiers(state)) == (
        {"buy-0-1": Decimal("5.0000")},
        {"buy-0-1": None},
    )


def test_a_buy_below_the_min_quantity_is_rejected_with_the_minimum():
    world = tiered_chip_world(min_quantity="500.000")

    state = closed_period(world, 1, {1: [buy("400"), buy("500")]})

    assert outcome_numbers(state) == [
        (False, "below_min_quantity", Decimal("400.000"), Decimal("500.000")),
        (True, None, None, None),
    ]


def test_the_min_quantity_holds_per_order_so_splitting_a_buy_changes_the_state():
    world = tiered_chip_world(min_quantity="500.000")

    split = closed_period(world, 1, {1: [buy("300"), buy("300")]})
    whole = closed_period(world, 1, {1: [buy("600")]})

    assert [outcome.reason for outcome in split.outcomes] == ["below_min_quantity"] * 2
    assert [outcome.accepted for outcome in whole.outcomes] == [True]


def test_an_express_buy_arrives_after_the_express_lead_time_at_the_express_price():
    world = express_world()

    state = started(world, 3, {2: [buy("100", express=True)]})

    payments = [row.amount for row in state.ledger if row.kind == "material_payment"]
    assert payments == [Decimal("-650")]
    [order] = placed_orders(world, {2: [buy("100", express=True)]})
    assert (order.unit_price, order.express) == (Decimal("6.5000"), True)


def test_a_late_express_and_a_normal_buy_of_one_period_share_their_outcome():
    world = express_world(punctuality="0.0000", delay=2, completeness="0.9000")
    decisions = {2: [buy("100", express=True), buy("50")]}

    assert arrivals(world, decisions) == [
        (5, "buy-2-1", Decimal("90.000")),
        (8, "buy-2-2", Decimal("45.000")),
    ]


def test_the_express_price_adds_the_express_cost_to_the_changed_price():
    rise = {
        "kind": "price_change",
        "target": ["chip"],
        "start": 2,
        "duration": 1,
        "factor": "1.2000",
    }
    decisions = {2: [buy("100", express=True)]}

    [order] = placed_orders(express_world([rise]), decisions)
    [exact] = placed_orders(express_world([rise], price="5.1234"), decisions)

    assert order.unit_price == Decimal("7.5000")
    assert exact.unit_price == Decimal("7.6481")


def test_an_express_buy_from_an_entry_without_express_is_rejected_as_no_express():
    world = express_world(express_lead_time=None, express_cost=None)

    state = first_period(world, [buy("100", express=True)])

    [outcome] = state.outcomes
    assert (outcome.accepted, outcome.reason) == (False, "no_express")
    assert (outcome.asked, outcome.available) == (None, None)


def test_the_max_quantity_counts_express_and_normal_buys_together():
    world = express_world(max_quantity="150.000")

    state = first_period(world, [buy("100"), buy("60", express=True)])

    assert outcome_numbers(state) == [
        (True, None, None, None),
        (False, "over_max_quantity", Decimal("60.000"), Decimal("50.000")),
    ]


def test_two_buys_of_one_material_from_one_supplier_in_a_period_arrive_together():
    manifest = chip_terms(tiny_manifest(), lead_time="2", punctuality="0.0000")
    world = draw_world_of_bodies(manifest, tiny_scenario())

    closed = first_period(world, [buy("10"), buy("20")])

    # Placed in period 1 with a lead time of 2 and never on time, late by the delay
    # of 1: both arrive in period 4.
    assert [
        (order.id, order.quantity, order.arrival) for order in closed.supplier_orders
    ] == [
        ("buy-1-1", Decimal("10.000"), 4),
        ("buy-1-2", Decimal("20.000"), 4),
    ]


@pytest.mark.property
@given(linear_factories(), seeds, st.data())
def test_orders_of_one_material_from_one_supplier_in_a_period_share_one_outcome(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed=seed)
    state = start_period(build_state(world), world)
    pair = data.draw(st.sampled_from(sorted(world.deliveries)))
    supplier, material = pair.split("/")
    warehouse = data.draw(
        st.sampled_from(
            [
                warehouse_id
                for warehouse_id, warehouse in world.factory.warehouses.items()
                if "materials" in warehouse.accepts
            ]
        )
    )
    named = {"warehouse": warehouse}
    twice = [
        buy("0.001", material, supplier) | named,
        buy("0.002", material, supplier) | named,
    ]

    closed = advance_period(state, world, submission(1, twice))

    accepted = [outcome for outcome in closed.outcomes if outcome.accepted]
    orders = [order for order in closed.supplier_orders if order.placed == 1]
    assert len(orders) == len(accepted)
    assert len({order.arrival for order in orders}) <= 1


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_every_accepted_buy_is_priced_at_the_price_of_its_placing_period(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(
        priced_every_period(factory), seed, data.draw, lambda world, _: buy_lists(world)
    )

    for _, _, closed in steps:
        placed = [
            order for order in closed.supplier_orders if order.placed == closed.period
        ]
        for order in placed:
            assert order.unit_price == expected_unit_price(world, order)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(drawn_runs())
def test_the_unit_price_is_the_price_of_the_highest_tier_reached_at_placing(
    run: tuple[World, list[RunStep]],
):
    world, steps = run

    for order in supplier_orders_of(world, steps).values():
        path = f"suppliers.{order.supplier}.catalogue.{order.material}"
        pair_prices = world.prices.get(f"{order.supplier}/{order.material}")
        written = world.parameters.get(f"{path}.price")
        if order.placed == 0:
            first = written if pair_prices is None else pair_prices[0]
            assert order.unit_price == first
            assert order.tier is None
            continue
        entry = world.factory.suppliers[order.supplier].catalogue[order.material]
        reached = [
            tier.from_ for tier in entry.discounts if tier.from_ <= order.quantity
        ]
        tier = max(reached, default=None)
        assert order.tier == tier
        if tier is not None:
            price = world.parameters[f"{path}.discounts.{tier}.price"]
        elif pair_prices is not None:
            price = pair_prices[order.placed - 1]
        else:
            price = world.parameters[f"{path}.price"]
        changed = price * acting_factor(
            world, "price_change", order.material, order.placed
        )
        expected = changed.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
        if order.express:
            expected += world.parameters[f"{path}.express_cost"]
        assert order.unit_price == expected


@pytest.mark.property
def test_buys_with_a_tier_are_reached():
    reached, drawn = count_reached(drawn_runs(), places_a_buy_with_a_tier)

    assert reached * 10 >= drawn, (reached, drawn)
