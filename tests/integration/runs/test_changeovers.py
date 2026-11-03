from decimal import Decimal

from factories import (
    api_client,
    changeover_manifest,
    get,
    produce,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)


def test_the_observation_shows_the_item_each_line_is_set_for():
    with api_client() as client:
        run = start_run(client, changeover_manifest())
        path = f"/runs/{run['id']}/observation"
        seen = [get(client, path)[1]["lines"]["line-1"]["set_for"]]
        for period, item in ((1, "monitor"), (2, "board"), (3, None)):
            decisions = [produce(item, "1")] if item else []
            submit(client, run["id"], period, decisions)
            seen.append(get(client, path)[1]["lines"]["line-1"]["set_for"])

    assert seen == [None, "monitor", "board", "board"]


def test_the_measures_of_changeovers_per_line_sum_to_the_total():
    scenario = tiny_scenario()
    scenario["start"]["set_for"] = {"line-1": "board"}
    decisions = {
        1: [produce("monitor", "1"), produce("board", "1"), produce("monitor", "1")]
    }
    with api_client() as client:
        run = start_run(client, changeover_manifest(), scenario)
        run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")

    line = result["measures"]["lines"]["line-1"]
    assert line["changeovers"] == 3
    assert line["changeover_hours"] == 3
    assert line["changeover_cost"] == Decimal(150)
    assert result["measures"]["total"]["changeover_cost"] == Decimal(150)
    assert result["terms"]["changeover_cost"] == Decimal(150)


# 90 boards take 90 * 0.100 = 9 hours; with the changeover of 1 hour they use the whole
# capacity of 10 hours, so one more board does not fit.
def test_a_changeover_and_a_produce_use_the_hours_up_to_the_limit():
    manifest = tiny_manifest()
    for terms in manifest["lines"]["line-1"]["items"].values():
        terms.update(changeover_time="1.000")
    scenario = tiny_scenario()
    scenario["horizon"] = 1
    scenario["start"]["stock"]["main"]["chip"] = "200"
    decisions = [produce("board", "90"), produce("board", "1")]
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, {1: decisions})
        _, periods = get(client, f"/runs/{run['id']}/periods")

    period = periods["periods"][0]
    outcomes = [
        outcome for step in period["steps"] for outcome in step.get("outcomes", [])
    ]
    assert [outcome["accepted"] for outcome in outcomes] == [True, False]
    rejected = outcomes[1]
    assert rejected["reason"] == "not_enough_hours"
    assert (rejected["asked"], rejected["available"]) == (Decimal("0.100"), 0)
    measures = period["steps"][-1]["measures"]["lines"]["line-1"]
    assert (measures["regular_hours"], measures["changeover_hours"]) == (9, 1)
