from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10
BOARDS = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "5"}
MONITOR = {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "1"}
GROUPED = {
    period: [BOARDS if period <= 5 else MONITOR] for period in range(1, HORIZON + 1)
}
ALTERNATING = {
    period: [BOARDS if period % 2 else MONITOR] for period in range(1, HORIZON + 1)
}


def run_of(decisions: dict[int, list[Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(wear_per_period="0.0000", wear_per_hour="0.0000")
    for terms in manifest["lines"]["line-1"]["items"].values():
        terms.update(changeover_time="1.000", changeover_cost="50.0000")
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    return periods, result


def test_grouping_each_item_pays_fewer_changeovers_than_alternating():
    runs = [run_of(GROUPED), run_of(ALTERNATING)]
    # 5 boards and 1 monitor each take 0.5 hours; a change of item takes 1 hour, and
    # so does the first produce of a line set for no item.
    changed_in = [{1, 6}, set(range(1, HORIZON + 1))]

    for (periods, result), changed in zip(runs, changed_in, strict=True):
        hours = [
            (
                period["steps"][-1]["measures"]["lines"]["line-1"]["regular_hours"],
                period["steps"][-1]["measures"]["lines"]["line-1"]["changeover_hours"],
            )
            for period in periods["periods"]
        ]
        assert hours == [
            (Decimal("0.5"), 1 if period in changed else 0)
            for period in range(1, HORIZON + 1)
        ]
        assert_run_balances(periods, result)
    grouped, alternating = (
        result["measures"]["lines"]["line-1"]["changeovers"] for _, result in runs
    )
    assert (grouped, alternating) == (2, HORIZON)
