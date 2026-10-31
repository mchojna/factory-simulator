from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast

import httpx2 as httpx
import pytest
from factories import (
    Client,
    api_client,
    draw_world_of_bodies,
    example_count,
    get,
    observed_decision_lists,
    post,
    run_to_the_end,
    seeds,
    small_factories,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.schemas.run import (
    ChecksPublic,
    ObservationPublic,
    ResultPublic,
)
from factory_simulator.engine import World

FactoryBodies = tuple[dict[str, Any], dict[str, Any]]
MARKER = "marker-7f3a9c"
FIRST_OBSERVATION = b"""
{"period": 1, "horizon": 5, "finished": false, "cash": 1000, "receivables": [],
 "stock": {"main": {"board": 10, "chip": 100, "monitor": 5}},
 "space": {"main": {"used": 1.95, "reserved": 0, "capacity": 100}},
 "lines": {"line-1": {"condition": 1, "set_for": null, "regular_hours_available": 10,
   "repair_hours_available": 10, "overtime_hours_available": 0}},
 "production": [], "plans": [], "transfers": [], "supplier_orders": [],
 "disruptions": [], "forecasts": {}, "prices": {},
 "outcomes": [],
 "customer_orders": [{"id": "order-1-1", "customer": "distributor",
   "product": "monitor", "quantity": 4, "shipped": 0, "arrival": 1, "due": 1,
   "last": 2}],
 "events": [{"kind": "customer_order", "step": "apply_events",
   "reference": "order-1-1", "customer": "distributor", "product": "monitor",
   "quantity": 4, "due": 1, "last": 2}]}
"""


def answer_of(response: httpx.Response) -> dict[str, Any]:
    return cast(dict[str, Any], read_json_bytes(response.content))


# Every answer while a run plays from a period to its end, its decisions drawn from
# each observation: the run, the observation, the periods, a check of the decisions
# and the answer of their submission, the last one included, each with the period
# whose events it may show.
def answers_until_the_end(
    client: Client, world: World, run_id: str, period: int, data: st.DataObject
) -> list[tuple[int, str, httpx.Response]]:
    path = f"/api/v1/runs/{run_id}"
    answers: list[tuple[int, str, httpx.Response]] = []
    while True:
        observation = client.get(f"{path}/observation")
        answers += [
            (period, "run", client.get(path)),
            (period, "observation", observation),
            (period, "periods", client.get(f"{path}/periods")),
        ]
        observed = answer_of(observation)
        decisions = data.draw(observed_decision_lists(world, observed))
        body = write_json({"period": period, "decisions": decisions})
        answers.append((period, "check", client.post(f"{path}/checks", content=body)))
        submitted = client.post(f"{path}/decisions", content=body)
        answers.append((period + 1, "submission", submitted))
        if answer_of(submitted).get("finished", False):
            return answers
        period += 1


def mappings_in(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        yield mapping
        for item in mapping.values():
            yield from mappings_in(item)
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            yield from mappings_in(item)


def events_by_period(periods: dict[str, Any]) -> dict[int, list[Any]]:
    return {
        period["period"]: [
            event for step in period["steps"] for event in step.get("events", [])
        ]
        for period in periods["periods"]
    }


def events_in(answer: dict[str, Any]) -> list[Any]:
    if "periods" in answer:
        return [
            event for events in events_by_period(answer).values() for event in events
        ]
    return answer.get("events", [])


def placed_by_a_buy(order: dict[str, Any]) -> bool:
    return not str(order["id"]).startswith("buy-0-")


# Every answer of a run holds no seed, no scenario text, nothing private, no arrival
# of an order placed by a buy, and no event of a period after its own.
def assert_private(
    answers: list[tuple[int, str, httpx.Response]],
    seed: int,
    periods: dict[str, Any],
) -> None:
    events = events_by_period(periods)
    for period, _, response in answers:
        text = response.text
        assert str(seed) not in text
        assert MARKER not in text
        for private in ('"private"', '"forecast_errors"', '"deliveries"', '"yields"'):
            assert private not in text
        answer = answer_of(response)
        for mapping in mappings_in(answer):
            assert "seed" not in mapping
            buy = str(mapping.get("id", "")).startswith("buy-")
            assert not (buy and placed_by_a_buy(mapping) and "arrival" in mapping)
        happened = [
            event
            for earlier in range(1, period + 1)
            for event in events.get(earlier, [])
        ]
        for event in events_in(answer):
            assert event in happened


def test_the_first_observation_of_the_tiny_factory_shows_every_field():
    with api_client() as client:
        run = start_run(client)
        _, observation = get(client, f"/runs/{run['id']}/observation")

    assert observation == read_json_bytes(FIRST_OBSERVATION)


def test_a_written_disruption_is_seen_in_its_periods_only_and_not_described():
    scenario = tiny_scenario()
    cut = {
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": 2,
        "duration": 2,
        "strength": "0.5",
    }
    scenario["disruptions"] = [cut]
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        seen = [observation["disruptions"]]
        for period in range(1, 5):
            _, observation = submit(client, run["id"], period, [])
            seen.append(observation["disruptions"])
        _, described = get(client, f"/runs/{run['id']}")

    shown = {
        "id": "disruption-1",
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": 2,
        "duration": 2,
        "strength": Decimal("0.5"),
    }
    assert seen == [[], [shown], [shown], [], []]
    assert "disruptions" not in described["description"]["scenario"]


def test_a_late_buy_shows_its_expected_arrival_until_it_arrives():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["punctuality"] = "0"
    buy = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
    with api_client() as client:
        run = start_run(client, manifest=manifest)
        observations = [submit(client, run["id"], 1, [buy | {"quantity": "50"}])[1]]
        for period in (2, 3):
            observations.append(submit(client, run["id"], period, [])[1])

    expected = [
        [order["expected_arrival"] for order in observation["supplier_orders"]]
        for observation in observations
    ]
    arrived = [
        event["reference"]
        for event in observations[2]["events"]
        if event["kind"] == "delivery"
    ]
    assert expected == [[3], [3], []]
    assert arrived == ["buy-1-1"]


def test_the_first_observation_lists_the_starting_orders():
    scenario = tiny_scenario()
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "3", "due": 2}
    ]
    scenario["start"]["supplier_orders"] = [
        {"supplier": "chip-maker", "material": "chip", "quantity": "20", "arrival": 4}
    ]
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        _, observation = get(client, f"/runs/{run['id']}/observation")

    assert [order["id"] for order in observation["customer_orders"]] == [
        "order-0-1",
        "order-1-1",
    ]
    assert observation["supplier_orders"] == [
        {
            "id": "buy-0-1",
            "supplier": "chip-maker",
            "material": "chip",
            "warehouse": "main",
            "quantity": Decimal(20),
            "open_quantity": Decimal(20),
            "unit_price": Decimal("0.5"),
            "express": False,
            "placed": 0,
            "expected_arrival": 4,
        }
    ]


def test_the_description_shows_a_drawn_price_and_a_punctuality_range_as_written():
    manifest = tiny_manifest()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip["price"] = {"min": "0.4000", "max": "0.6000"}
    chip["punctuality"] = {"min": "0.8000", "max": "0.9000"}
    with api_client() as client:
        run = start_run(client, manifest=manifest)
        _, described = get(client, f"/runs/{run['id']}")
        _, world = get(client, f"/runs/{run_to_the_end(client, run)['id']}/world")

    entry = described["description"]["manifest"]["suppliers"]["chip-maker"]
    path = "suppliers.chip-maker.catalogue.chip"
    assert (
        entry["catalogue"]["chip"]["price"]
        == (world["parameters"][f"{path}.price"]["value"])
    )
    assert entry["catalogue"]["chip"]["punctuality"] == {
        "min": Decimal("0.8"),
        "max": Decimal("0.9"),
        "distribution": "uniform",
        "cut_mean": Decimal("0.85"),
    }


def test_each_observation_shows_the_price_of_its_period_and_the_description_its_range():
    manifest = tiny_manifest()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip["price"] = {"min": "0.4000", "max": "0.6000", "drawn": "period"}
    with api_client() as client:
        run = start_run(client, manifest=manifest)
        _, described = get(client, f"/runs/{run['id']}")
        _, observation = get(client, f"/runs/{run['id']}/observation")
        seen: list[Any] = []
        while "prices" in observation:
            seen.append(observation["prices"])
            _, observation = submit(client, run["id"], observation["period"], [])
        _, world = get(client, f"/runs/{run['id']}/world")

    prices = world["prices"]["chip-maker/chip"]
    assert len(set(prices)) > 1
    assert seen == [{"chip-maker": {"chip": price}} for price in prices]
    assert described["description"]["manifest"]["suppliers"]["chip-maker"]["catalogue"][
        "chip"
    ]["price"] == {
        "min": Decimal("0.4"),
        "max": Decimal("0.6"),
        "distribution": "uniform",
        "drawn": "period",
        "cut_mean": Decimal("0.5"),
    }


def test_the_description_holds_the_demand_shapes_and_no_other_scenario_key():
    shapes = [
        {"kind": "trend", "target": "all", "rate": "0.1"},
        {
            "kind": "step",
            "target": {"customer": "distributor"},
            "period": 3,
            "factor": "2",
        },
    ]
    scenario = tiny_scenario()
    scenario["demand_shapes"] = shapes
    scenario["description"] = "A trend and a step."
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        _, described = get(client, f"/runs/{run['id']}")

    written = described["description"]["scenario"]
    assert sorted(written) == [
        "demand_shapes",
        "forecasts",
        "hidden",
        "horizon",
        "random_disruptions",
        "start",
    ]
    assert written["demand_shapes"] == [
        shapes[0] | {"rate": Decimal("0.1")},
        shapes[1] | {"factor": Decimal(2)},
    ]
    assert written["forecasts"] == []


# Chips of 100.001 take 100.001 * 0.010 = 1.00001 of space, beside 0.2 of boards and
# 0.75 of monitors: 1.95001, a number of 5 places. Each body is read with exact
# numbers, as a client of the HTTP interface reads it.
def test_every_answer_of_a_run_with_5_places_of_space_validates_as_its_model():
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["chip"] = "100.001"
    repair = {"kind": "repair", "line": "line-1", "amount": "0.0600"}
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=0)
        _, observed = submit(client, run["id"], 1, [repair])
        observation = client.get(f"/api/v1/runs/{run['id']}/observation")
        check = client.post(
            f"/api/v1/runs/{run['id']}/checks",
            content=write_json({"period": 2, "decisions": [repair]}),
        )
        run_to_the_end(client, run | {"period": 2})
        result = client.get(f"/api/v1/runs/{run['id']}/result")

    assert observed["outcomes"][0] | {"decision": None} == {
        "decision_id": "1-1",
        "decision": None,
        "accepted": False,
        "reason": "over_full_condition",
        "asked": Decimal("0.0600"),
        "available": Decimal("0.0000"),
    }
    seen = ObservationPublic.model_validate(answer_of(observation))
    assert seen.space["main"].used == Decimal("1.95001")
    ChecksPublic.model_validate(answer_of(check))
    ResultPublic.model_validate(answer_of(result))


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), st.integers(10**20, 2**128 - 1), st.data())
def test_no_answer_of_a_run_a_check_or_a_fork_shows_the_seed_the_world_or_the_future(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    scenario = scenario | {"name": MARKER, "description": MARKER}
    world = draw_world_of_bodies(manifest, scenario, seed)
    horizon = int(scenario["horizon"])
    fork_period = data.draw(st.integers(1, horizon))
    with api_client() as client:
        _, created_manifest = post(client, "/manifests", manifest)
        _, created_scenario = post(
            client, f"/manifests/{created_manifest['id']}/scenarios", scenario
        )
        body = write_json({"scenario_id": created_scenario["id"], "seed": seed})
        started = client.post("/api/v1/runs", content=body)
        run_id = started.json()["id"]
        answers = [(1, "start", started)]
        answers += answers_until_the_end(client, world, run_id, 1, data)
        forked = client.post(
            f"/api/v1/runs/{run_id}/forks", content=f'{{"period": {fork_period}}}'
        )
        fork_id = forked.json()["id"]
        fork_answers = [(fork_period, "fork", forked)]
        fork_answers += answers_until_the_end(client, world, fork_id, fork_period, data)
        _, periods = get(client, f"/runs/{run_id}/periods")
        _, fork_periods = get(client, f"/runs/{fork_id}/periods")

    assert_private(answers, seed, periods)
    assert_private(fork_answers, seed, fork_periods)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_every_event_of_a_period_is_in_the_next_observation_once(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed)
    with api_client() as client:
        run = start_run(client, *factory, seed)
        answers = answers_until_the_end(client, world, run["id"], 1, data)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    observations = [
        answer_of(response) for _, kind, response in answers if kind == "observation"
    ]

    closing: list[Any] = []
    for period, observation in zip(periods["periods"], observations, strict=True):
        steps = {step["step"]: step for step in period["steps"]}
        expected = [
            *closing,
            *steps["receive_deliveries"]["events"],
            *steps["apply_events"]["events"],
        ]
        assert observation["events"] == expected
        closing = steps["close_period"]["events"]
