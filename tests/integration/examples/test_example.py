import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from factories import (
    LIBRARY,
    Client,
    api_client,
    assert_run_balances,
    database_file,
    example_bodies,
    example_count,
    example_scenario,
    get,
    post,
    run_to_the_end,
    seeds,
    submit,
)
from hypothesis import given, settings

from factory_simulator.api.core.json import write_json

MATERIALS = {
    "microchip",
    "microchip-b",
    "passive-kit",
    "pcb-blank",
    "lcd-panel",
    "connector-pins",
    "copper-wire",
    "plastic-resin",
    "steel-sheet",
}
COMPONENTS = {
    "control-board",
    "power-module",
    "sensor-module",
    "display-unit",
    "enclosure",
    "cable-harness",
}
NEW_DEVICES = ("smart-monitor", "sensor-gateway")
NAME = "Electronics factory with economies of scale"
DESCRIPTION = (
    "The electronics factory with minimum quantities, discounts and changeovers: "
    "large buys and long production runs cost less per unit."
)
REPOSITORY = Path(__file__).resolve().parents[3]
QUICK_START = REPOSITORY / "docs" / "development" / "en" / "start" / "quick-start.md"
HIDDEN = [
    "customers.products.demand",
    "suppliers.catalogue.punctuality",
    "suppliers.catalogue.delay",
    "suppliers.catalogue.completeness",
    "suppliers.catalogue.acceptance",
    "lines.items.yield",
    "lines.breakdown_chance",
    "lines.breakdown_loss",
    "disruptions.duration",
]
# The places of each kind of drawn value: 3 for quantities, 4 for shares and money,
# none for periods.
PLACES = {
    "price": 4,
    "punctuality": 4,
    "demand": 3,
    "yield": 4,
    "delay": 0,
    "lead_time": 0,
    "completeness": 4,
    "acceptance": 4,
    "breakdown_loss": 4,
}


# One period of the example from one unit of every material, so that each is at hand.
def one_period() -> dict[str, Any]:
    stock = {"main-plant": dict.fromkeys(MATERIALS, "1")}
    return {"horizon": 1, "start": {"cash": "0", "stock": stock}}


# The example manifest, as the server stores it.
def the_example(client: Client) -> dict[str, Any]:
    manifest, _ = example_bodies("steady-market")
    _, created = post(client, "/manifests", manifest)
    return created


def width(demand: object) -> Decimal:
    if not isinstance(demand, dict):
        return Decimal(0)
    value_range = cast(dict[str, Decimal], demand)
    low, high = value_range["min"], value_range["max"]
    return (high - low) / ((high + low) / 2)


def finished_run_of_example(
    client: Client,
    scenario: dict[str, Any] | None = None,
    seed: int = 1,
) -> tuple[str, dict[str, Any]]:
    manifest_id = the_example(client)["id"]
    _, created = post(
        client, f"/manifests/{manifest_id}/scenarios", scenario or example_scenario()
    )
    _, run = post(client, "/runs", {"scenario_id": created["id"], "seed": seed})
    run_to_the_end(client, run)
    return manifest_id, run


def range_of(content: dict[str, Any], path: str, origin: str) -> object:
    if origin == "written":
        found: Any = content
        for key in path.split("."):
            found = found[key]
        return found
    name = path.rsplit(".", 1)[-1]
    defaults = content["groups"][origin]["defaults"]
    [group_value] = [terms[name] for terms in defaults.values() if name in terms]
    return group_value


def groups_of_item(content: dict[str, Any], item: str) -> list[str]:
    for kind in ("materials", "components", "products"):
        if item in content[kind]:
            return content[kind][item].get("groups", [])
    raise KeyError(item)


def resolved(
    content: dict[str, Any],
    terms: dict[str, Any],
    groups: list[str],
    section: str,
    name: str,
) -> object:
    if name in terms:
        return terms[name]
    for group in groups:
        defaults = content["groups"][group]["defaults"].get(section, {})
        if name in defaults:
            return defaults[name]
    raise KeyError(name)


def check_drawn(value: object, value_range: object, name: str) -> None:
    number = Decimal(cast(Decimal, value))
    if isinstance(value_range, dict):
        limits = cast(dict[str, Decimal], value_range)
        assert Decimal(limits["min"]) <= number <= Decimal(limits["max"])
    else:
        assert number == Decimal(cast(Decimal, value_range))
    assert number == number.quantize(Decimal(1).scaleb(-PLACES[name]))


def expected_arrival_of_a_buy(supplier: str) -> int:
    buy = {
        "kind": "buy",
        "supplier": supplier,
        "material": "passive-kit",
        "quantity": "100",
        "warehouse": "main-plant",
    }
    with api_client() as client:
        manifest_id = the_example(client)["id"]
        path = f"/manifests/{manifest_id}/scenarios"
        _, scenario = post(client, path, example_scenario())
        _, run = post(client, "/runs", {"scenario_id": scenario["id"], "seed": 1})
        _, observation = submit(client, run["id"], 1, [buy])
    [order] = observation["supplier_orders"]
    return order["expected_arrival"]


def test_a_server_with_examples_lists_the_example_manifest_and_its_scenarios_only():
    with api_client(load_examples=True) as client:
        _, listed = get(client, "/manifests")
        [summary] = listed["manifests"]
        _, manifest = get(client, f"/manifests/{summary['id']}")
        _, scenarios = get(client, f"/manifests/{summary['id']}/scenarios")
    with api_client() as client:
        _, without = get(client, "/manifests")

    assert [manifest["name"] for manifest in listed["manifests"]] == [NAME]
    assert sorted(scenario["name"] for scenario in scenarios["scenarios"]) == sorted(
        LIBRARY
    )
    assert len(LIBRARY) == 23
    content = manifest["content"]
    assert content["name"] == NAME
    assert set(content["materials"]) == MATERIALS
    assert set(content["components"]) == COMPONENTS
    assert set(content["products"]) == {
        "industrial-controller",
        "smart-monitor",
        "sensor-gateway",
    }
    assert set(content["suppliers"]) == {
        "apac-chips",
        "emea-electronic-parts",
        "amer-metals",
        "apac-displays-plastics",
    }
    assert set(content["customers"]) == {
        "tier1-distributor",
        "equipment-maker",
        "retail-chain",
        "system-integrator",
    }
    assert set(content["lines"]) == {
        "smt-line",
        "module-assembly-line",
        "moulding-line",
        "final-assembly-line",
    }
    assert set(content["warehouses"]) == {"main-plant", "distribution-centre"}
    assert without == {"manifests": []}


def test_the_quick_start_gives_the_name_and_the_description_of_the_listed_example():
    with api_client(load_examples=True) as client:
        _, listed = get(client, "/manifests")

    [summary] = listed["manifests"]
    text = " ".join(QUICK_START.read_text().split())
    found = re.search(r"has the name `([^`]+)` and the description `([^`]+)`", text)

    assert sorted(summary) == ["description", "id", "name"]
    assert (summary["name"], summary["description"]) == (NAME, DESCRIPTION)
    assert found, "the quick start gives no name and description of the example"
    assert (found[1], found[2]) == (NAME, DESCRIPTION)


def test_a_second_start_creates_no_manifest_or_scenario_again():
    with database_file() as url:
        listings: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for _ in range(2):
            with api_client(url, load_examples=True) as client:
                _, manifests = get(client, "/manifests")
                [summary] = manifests["manifests"]
                _, scenarios = get(client, f"/manifests/{summary['id']}/scenarios")
            listings.append((manifests, scenarios))

    first, second = listings
    assert second == first
    assert len(first[1]["scenarios"]) == 23


def test_new_devices_are_wider_dearer_to_delay_and_less_patient():
    with api_client() as client:
        content = the_example(client)["content"]
        _, run = finished_run_of_example(client, one_period())
        _, world = get(client, f"/runs/{run['id']}/world")

    parameters = world["parameters"]
    for customer, terms in content["customers"].items():
        controller = terms["products"].get("industrial-controller")
        devices = [device for device in NEW_DEVICES if device in terms["products"]]
        if controller is None or not devices:
            continue
        assert controller["demand"]["distribution"] == "normal"
        for device in devices:
            assert terms["products"][device]["demand"]["distribution"] == "lognormal"
            assert width(terms["products"][device]["demand"]) > width(
                controller["demand"]
            )
            path = f"customers.{customer}.products"
            for key, larger in (("late_penalty", True), ("patience", False)):
                new = parameters[f"{path}.{device}.{key}"]["value"]
                old = parameters[f"{path}.industrial-controller.{key}"]["value"]
                assert (new > old) if larger else (new < old)


@pytest.mark.slow
def test_the_example_has_economies_of_scale_and_its_runs_are_not_linear():
    with api_client() as client:
        manifest = the_example(client)
        _, run = finished_run_of_example(client)

    content = manifest["content"]
    suppliers = content["suppliers"]
    chips = suppliers["apac-chips"]["catalogue"]["microchip"]
    parts = suppliers["emea-electronic-parts"]["catalogue"]
    panels = suppliers["apac-displays-plastics"]["catalogue"]["lcd-panel"]
    assert chips["min_quantity"] == Decimal(500)
    assert panels["min_quantity"] == Decimal(100)
    assert "discounts" in chips
    assert "discounts" in parts["passive-kit"]
    assert "discounts" in parts["pcb-blank"]
    control_board = content["lines"]["smt-line"]["items"]["control-board"]
    assert "changeover_cost" in control_board
    assert manifest["linear"] is False
    assert run["description"]["linear"] is False


def test_with_every_group_hidden_the_description_holds_none_of_them():
    with api_client() as client:
        scenario = one_period() | {"hidden": HIDDEN}
        _, run = finished_run_of_example(client, scenario)

    described = write_json(run["description"]["manifest"]).decode()
    for key in (
        '"demand"',
        '"demand_persistence"',
        '"punctuality"',
        '"delay"',
        '"completeness"',
        '"acceptance"',
        '"yield"',
        '"breakdown_chance"',
        '"breakdown_loss"',
    ):
        assert key not in described


def test_the_world_names_the_group_of_every_value_a_group_gives():
    with api_client() as client:
        content = the_example(client)["content"]
        _, run = finished_run_of_example(client, one_period())
        _, world = get(client, f"/runs/{run['id']}/world")

    origins = {path: terms["origin"] for path, terms in world["parameters"].items()}
    assert origins["suppliers.apac-chips.catalogue.microchip.lead_time"] == "apac"
    assert (
        origins["customers.retail-chain.products.smart-monitor.late_penalty"]
        == "new-devices"
    )
    groups = set(content["groups"])
    assert {origin for origin in origins.values()} - {"written", "default"} <= groups


def test_a_new_device_not_shipped_by_its_due_period_pays_its_late_penalty():
    scenario = example_scenario()
    scenario["horizon"] = 4
    with api_client() as client:
        _, run = finished_run_of_example(client, scenario)
        _, result = get(client, f"/runs/{run['id']}/result")

    products = result["measures"]["products"]
    for device in NEW_DEVICES:
        assert products[device]["late_penalty"] > 0


def test_passive_kits_from_amer_arrive_a_period_before_those_from_emea():
    assert expected_arrival_of_a_buy("amer-metals") == 2
    assert expected_arrival_of_a_buy("emea-electronic-parts") == 3


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(seeds)
def test_every_run_of_the_example_draws_within_ranges_and_balances(seed: int):
    with api_client() as client:
        content = the_example(client)["content"]
        _, run = finished_run_of_example(client, seed=seed)
        _, world = get(client, f"/runs/{run['id']}/world")
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods_of_run = get(client, f"/runs/{run['id']}/periods")

    horizon = example_scenario()["horizon"]
    periods = list(range(1, horizon + 1))

    for path, parameter in world["parameters"].items():
        if parameter["drawn"]:
            value_range = range_of(content, path, parameter["origin"])
            assert isinstance(value_range, dict)
            name = path.rsplit(".", 1)[-1]
            check_drawn(parameter["value"], cast(dict[str, Decimal], value_range), name)
    pairs = [
        (customer_id, product_id)
        for customer_id, customer in content["customers"].items()
        for product_id in customer["products"]
    ]
    assert sorted(world["demand"]) == sorted(
        f"{customer}/{product}" for customer, product in pairs
    )
    for customer_id, product_id in pairs:
        customer = content["customers"][customer_id]
        groups = customer.get("groups", []) + groups_of_item(content, product_id)
        terms = customer["products"][product_id]
        value_range = resolved(content, terms, groups, "customer_products", "demand")
        demand = world["demand"][f"{customer_id}/{product_id}"]
        assert len(demand) == horizon
        for value in demand:
            check_drawn(value, value_range, "demand")
    entries = [
        (supplier_id, material_id)
        for supplier_id, supplier in content["suppliers"].items()
        for material_id in supplier["catalogue"]
    ]
    assert sorted(world["deliveries"]) == sorted(
        f"{supplier}/{material}" for supplier, material in entries
    )
    for supplier_id, material_id in entries:
        supplier = content["suppliers"][supplier_id]
        groups = supplier.get("groups", []) + groups_of_item(content, material_id)
        terms = supplier["catalogue"][material_id]
        deliveries = world["deliveries"][f"{supplier_id}/{material_id}"]
        assert [delivery["period"] for delivery in deliveries] == periods
        for name in ("delay", "completeness", "acceptance"):
            value_range = resolved(content, terms, groups, "catalogue", name)
            for delivery in deliveries:
                check_drawn(delivery[name], value_range, name)
    made = [
        (line_id, item_id)
        for line_id, line in content["lines"].items()
        for item_id in line["items"]
    ]
    assert sorted(world["yields"]) == sorted(f"{line}/{item}" for line, item in made)
    for line_id, item_id in made:
        line = content["lines"][line_id]
        groups = line.get("groups", []) + groups_of_item(content, item_id)
        terms = line["items"][item_id]
        value_range = resolved(content, terms, groups, "line_items", "yield")
        yields = world["yields"][f"{line_id}/{item_id}"]
        assert len(yields) == horizon
        for value in yields:
            check_drawn(value, value_range, "yield")
    assert sorted(world["breakdowns"]) == sorted(content["lines"])
    for line_id, line in content["lines"].items():
        groups = line.get("groups", [])
        value_range = resolved(content, line, groups, "lines", "breakdown_loss")
        breakdowns = world["breakdowns"][line_id]
        assert [breakdown["period"] for breakdown in breakdowns] == periods
        for breakdown in breakdowns:
            check_drawn(breakdown["loss"], value_range, "breakdown_loss")
    assert_run_balances(periods_of_run, result)
