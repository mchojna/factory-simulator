from decimal import Decimal
from typing import Any

from factories import api_client, get, start_run, submit, tiny_scenario

OUTAGE = {
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "start": 6,
    "duration": 2,
    "strength": "0.8000",
    "notice": 3,
}


def test_an_announced_outage_is_seen_from_start_less_notice_and_not_before():
    scenario = tiny_scenario() | {"horizon": 8, "disruptions": [OUTAGE]}
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        before: list[Any] = [run]
        seen: dict[int, Any] = {}
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period in range(1, 9):
            seen[period] = observation
            if period < 3:
                before += [observation, get(client, f"/runs/{run['id']}")[1]]
                before.append(get(client, f"/runs/{run['id']}/periods")[1])
            _, observation = submit(client, run["id"], period, [])
        _, world = get(client, f"/runs/{run['id']}/world")

    assert all("disruption-1" not in str(response) for response in before)
    shown = {
        "id": "disruption-1",
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": 6,
        "duration": 2,
        "strength": Decimal("0.8000"),
    }
    assert [seen[period]["disruptions"] for period in range(1, 9)] == [
        [],
        [],
        *[[shown]] * 5,
        [],
    ]
    assert [disruption["visible"] for disruption in world["disruptions"]] == [3]


def test_a_later_written_disruption_listed_first_does_not_reveal_an_earlier_number():
    cuts = [
        {
            "kind": "capacity_cut",
            "target": ["line-1"],
            "start": start,
            "duration": 1,
            "strength": "0.5000",
            "notice": 0,
        }
        for start in (7, 2)
    ]
    scenario = tiny_scenario() | {"horizon": 8, "disruptions": cuts}
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        submit(client, run["id"], 1, [])
        _, observation = get(client, f"/runs/{run['id']}/observation")

    assert observation["period"] == 2
    assert [
        (disruption["id"], disruption["start"])
        for disruption in observation["disruptions"]
    ] == [("disruption-1", 2)]
