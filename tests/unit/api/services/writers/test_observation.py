from decimal import Decimal
from typing import Any, cast

from factories import (
    draw_world_of_bodies,
    observation_in,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.services.writers.observation import observation_json


def test_an_announced_outage_hides_its_duration_when_durations_are_hidden():
    outage = {
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": 10,
        "duration": 3,
        "strength": "0.5000",
        "notice": 2,
    }
    scenario = tiny_scenario() | {"horizon": 14, "disruptions": [outage]}
    scenario["hidden"] = ["disruptions.duration"]
    world = draw_world_of_bodies(tiny_manifest(), scenario)

    written = observation_json(observation_in(world, 8), ("disruptions.duration",))

    assert cast(dict[str, Any], written)["disruptions"] == [
        {
            "id": "disruption-1",
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 10,
            "strength": Decimal("0.5000"),
        }
    ]
