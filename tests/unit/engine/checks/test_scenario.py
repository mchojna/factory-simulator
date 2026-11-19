from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    SCENARIO_EXAMPLES,
    FactoryBodies,
    ScenarioChange,
    chips_in_lead_time,
    plain_tiny_manifest,
    plain_tiny_scenario,
    small_factories,
    tiny_manifest,
    tiny_scenario,
    to_engine,
    transfer_bound_bodies,
)
from hypothesis import given

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.api.services.readers.scenario import to_scenario
from factory_simulator.engine import (
    Cash,
    Disruption,
    Factory,
    InputError,
    Material,
    RandomDisruption,
    Scenario,
    Warehouse,
    check_scenario,
)
from factory_simulator.engine.checks.scenario import (
    largest_demand_factor,
    largest_effect,
)
from factory_simulator.engine.rules.demand import shape_factor

ZERO = Decimal(0)

TOO_LARGE_FOR_THE_RECORD = (
    "horizon: a run of this scenario can exceed the numbers the record holds"
)


KINDS = (
    "supplier_outage, material_shortage, quality_drop, transport_delay, demand_shock, "
    "line_breakdown, price_change, capacity_cut, yield_drop"
)


def read_scenario(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
    factory = read_factory(read_json_bytes(write_json(manifest)))
    model = validate(ScenarioCreate, read_json_bytes(write_json(scenario)))
    check_scenario(to_scenario(model), factory)


def refusal_message(change: ScenarioChange) -> str:
    manifest, scenario = tiny_manifest(), tiny_scenario()
    change(manifest, scenario)
    with pytest.raises(InputError) as refusal:
        read_scenario(manifest, scenario)
    return str(refusal.value)


# The plain tiny factory for 4 periods with a demand of 2 * 10**20 halved from period 1.
def halved_demand_bodies() -> FactoryBodies:
    manifest, scenario = plain_tiny_manifest(), plain_tiny_scenario()
    pair = manifest["customers"]["distributor"]["products"]["monitor"]
    pair["demand"] = "200000000000000000000.000"
    halving = {"kind": "step", "target": "all", "period": 1, "factor": "0.5000"}
    scenario |= {"horizon": 4, "demand_shapes": [halving]}
    return manifest, scenario


def steel_in_one_warehouse(space: Decimal, capacity: Decimal) -> Factory:
    return Factory(
        materials={
            "steel": Material(space=space, storage_cost=ZERO, salvage_value=ZERO)
        },
        components={},
        products={},
        suppliers={},
        customers={},
        lines={},
        warehouses={"main": Warehouse(capacity=capacity)},
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in SCENARIO_EXAMPLES],
    ids=[name for name, _, _ in SCENARIO_EXAMPLES],
)
def test_an_invalid_scenario_is_refused_with_the_message_of_its_problem(
    change: ScenarioChange, message: str
):
    assert refusal_message(change) == message


def test_a_target_of_a_group_with_no_members_is_refused():
    manifest, scenario = tiny_manifest(), tiny_scenario()
    manifest["groups"] = {"apac": {"kind": "region"}}
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": {"region": "apac"},
            "start": 1,
            "duration": 1,
            "strength": "0.5000",
        }
    ]

    with pytest.raises(InputError) as refusal:
        read_scenario(manifest, scenario)

    assert str(refusal.value) == "disruptions.0.target: apac has no members"


def test_a_disruption_of_an_unknown_kind_is_refused_at_its_kind():
    factory, _ = to_engine(tiny_manifest(), tiny_scenario())
    flood = Disruption(
        id="disruption-1",
        kind="flood",
        target=None,
        start=1,
        duration=1,
        effect=Decimal("0.5000"),
    )

    with pytest.raises(InputError) as refusal:
        check_scenario(Scenario(horizon=5, disruptions=(flood,)), factory)

    assert str(refusal.value) == f"disruptions.0.kind: flood is not one of {KINDS}"


def test_a_random_disruption_of_an_unknown_kind_is_refused_at_its_kind():
    factory, _ = to_engine(tiny_manifest(), tiny_scenario())
    flood = RandomDisruption(
        name="flood",
        kind="flood",
        target=None,
        chance=Decimal("0.5000"),
        duration=1,
        effect=Decimal("0.5000"),
    )
    scenario = Scenario(horizon=5, random_disruptions=(flood,))

    with pytest.raises(InputError) as refusal:
        check_scenario(scenario, factory)

    assert str(refusal.value) == (
        f"random_disruptions.0.kind: flood is not one of {KINDS}"
    )


def test_the_tiny_scenario_passes_every_check():
    read_scenario(tiny_manifest(), tiny_scenario())


# A forecast one period ahead has only its increment within `noise`.
def test_a_noise_growth_of_forecasts_one_period_ahead_is_accepted():
    manifest, scenario = tiny_manifest(), tiny_scenario()
    forecast = {"periods_ahead": 1, "noise": "0.1000", "noise_growth": "0.0500"}
    scenario["forecasts"] = [{"target": "all"} | forecast]

    read_scenario(manifest, scenario)


def test_a_material_that_arrives_in_time_by_express_only_passes():
    manifest, scenario = tiny_manifest(), tiny_scenario()
    chips_in_lead_time(6, 2)(manifest, scenario)

    read_scenario(manifest, scenario)


def test_a_random_price_change_that_keeps_the_price_above_salvage_passes():
    manifest, scenario = tiny_manifest(), tiny_scenario()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "5.0000"
    manifest["materials"]["chip"]["salvage_value"] = "3.0000"
    scenario["random_disruptions"] = [
        {
            "name": "prices",
            "kind": "price_change",
            "target": ["chip"],
            "chance": "0.0100",
            "duration": 1,
            "factor": {"min": "0.7000", "max": "1.2000"},
        }
    ]

    read_scenario(manifest, scenario)


# U = 4 * 10 + 1000 + 10 + 100 / 0.01 + 115 = 11165 and A = 50, so the money bound is
# (1000 + 11165 * 5 * 5 * 50 * 12) * 1.0005 ** 5, about 1.68E+8.
def test_a_long_random_demand_shock_counts_its_factor_once():
    manifest, scenario = tiny_manifest(), tiny_scenario()
    scenario["random_disruptions"] = [
        {
            "name": "rush",
            "kind": "demand_shock",
            "target": ["monitor"],
            "chance": "0.0100",
            "duration": 30,
            "factor": "10.0000",
        }
    ]

    read_scenario(manifest, scenario)


def test_a_step_that_halves_demand_from_period_1_gives_a_demand_factor_of_a_half():
    factory, scenario = to_engine(*halved_demand_bodies())

    factor = largest_demand_factor("distributor", "monitor", scenario, factory)

    assert factor == Decimal("0.5")


# U = 2 * 10**20 * 0.5 + 1000 buys + 10 hours + 100 / 0.01 space + 24 started =
# 10**20 + 11034 and A = 50, so the money bound is 1000 + U * 4 * 4 * 50 * 12 =
# 960000000000000105927400, below 10**24; a factor of 1 would give twice as much.
def test_a_step_that_lowers_demand_lowers_the_money_bound_of_its_pair():
    read_scenario(*halved_demand_bodies())


# U = 10**23 / 10**22 = 10, so quantities stay at 10 * h and money at 0; space reaches
# 10 * h * 10**22, 9 * 10**23 at horizon 9 and 10**24 at horizon 10.
def test_the_space_a_run_can_fill_is_bounded_by_the_record():
    factory = steel_in_one_warehouse(Decimal(10) ** 22, Decimal(10) ** 23)

    check_scenario(Scenario(horizon=9), factory)
    with pytest.raises(InputError) as refusal:
        check_scenario(Scenario(horizon=10), factory)

    assert str(refusal.value) == TOO_LARGE_FOR_THE_RECORD


def test_a_warehouse_of_a_capacity_too_large_for_the_record_is_refused():
    factory = steel_in_one_warehouse(Decimal(1), Decimal(10) ** 24)

    with pytest.raises(InputError) as refusal:
        check_scenario(Scenario(horizon=1), factory)

    assert str(refusal.value) == TOO_LARGE_FOR_THE_RECORD


# U = 0.001 buys + 0.001 hours + 2000 / 1000 space + 1 started = 3.002 and A = 2 *
# 10**22, so the money bound is 1000 + 3.002 * 2 * 10**22 * 12 =
# 720480000000000000001000, below 10**24.
def test_the_world_of_repeated_immediate_transfers_passes_every_check():
    read_scenario(*transfer_bound_bodies())


# One period without demand from 2 chips and 2 boards: U = 0.001 buys + 1 hour + 10 /
# 1 space + 4 started = 15.001, and A = F = 10**19, the changeover or repair cost. Money
# is cash + 15.001 * (12 * 10**19 + 2000 * 10**19) = cash + 301820120000000000000000,
# 10**24 at a cash of 698179880000000000000000.
@pytest.mark.parametrize("cost", ["changeover", "repair"])
def test_the_money_bound_counts_1000_changeovers_and_repairs_a_unit(cost: str):
    manifest, scenario = plain_tiny_manifest(), plain_tiny_scenario()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item["space"] = "1.000"
    manifest["warehouses"]["main"]["capacity"] = "10.000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["max_quantity"] = "0.001"
    manifest["lines"]["line-1"]["capacity"] = "1.000"
    line = manifest["lines"]["line-1"]
    if cost == "changeover":
        line["items"]["board"]["changeover_cost"] = "10000000000000000000"
    else:
        line["repair_cost"] = "10000000000000000000"
    scenario["horizon"] = 1
    stock = {"main": {"chip": "2", "board": "2"}}
    scenario["start"] = {"cash": "698179879999999999999999", "stock": stock}

    read_scenario(manifest, scenario)
    scenario["start"]["cash"] = "698179880000000000000000"
    with pytest.raises(InputError) as refusal:
        read_scenario(manifest, scenario)

    assert str(refusal.value) == TOO_LARGE_FOR_THE_RECORD


@pytest.mark.property
@given(small_factories())
def test_shapes_that_only_lower_demand_leave_the_demand_factor_at_the_shocks(
    factory: FactoryBodies,
):
    engine_factory, scenario = to_engine(*factory)
    lowering = tuple(
        shape
        for shape in scenario.demand_shapes
        if all(
            shape_factor(shape, period) <= 1
            for period in range(1, scenario.horizon + 1)
        )
    )
    scenario = replace(scenario, demand_shapes=lowering)
    shocks = largest_effect(scenario, "demand_shock")

    for customer_id, customer in engine_factory.customers.items():
        for product_id in customer.products:
            factor = largest_demand_factor(
                customer_id, product_id, scenario, engine_factory
            )
            assert factor <= shocks


@pytest.mark.property
@given(small_factories())
def test_every_generated_scenario_passes_every_check(factory: FactoryBodies):
    read_scenario(*factory)
