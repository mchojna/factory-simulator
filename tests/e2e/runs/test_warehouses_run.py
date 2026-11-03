from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    produce,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10


def decisions_of(period: int) -> list[dict[str, Any]]:
    return [
        ship(f"order-{period}-1", "4", warehouse="plant"),
        produce("monitor", "4"),
        produce("board", "9"),
        buy("20", warehouse="plant"),
    ]


def test_a_plant_and_a_centre_of_products_run_with_balanced_items_and_cash():
    manifest = tiny_manifest()
    manifest["warehouses"] = {
        "plant": {"capacity": "100.000"},
        "centre": {"capacity": "100.000", "accepts": ["products"]},
    }
    manifest["lines"]["line-1"]["warehouse"] = "plant"
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"] = {
        "plant": {"chip": "100", "board": "10", "monitor": "5"}
    }
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    measures = result["measures"]
    end = measures["warehouses"]
    line = measures["lines"]
    accepted = measures["suppliers"]["chip-maker/chip"]["units_accepted"]
    assert 100 + accepted == (
        end["plant/chip"]["stock"] + 2 * line["line-1/board"]["units_started"]
    )
    assert 10 + line["line-1/board"]["units_good"] == (
        end["plant/board"]["stock"] + 2 * line["line-1/monitor"]["units_started"]
    )
    assert 5 + line["line-1/monitor"]["units_good"] == (
        end["plant/monitor"]["stock"] + measures["total"]["units_shipped"]
    )
    assert end["centre/monitor"]["stock"] == 0
    assert_run_balances(periods, result)
