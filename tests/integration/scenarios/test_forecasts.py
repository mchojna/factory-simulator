from typing import Any, cast

from factories import (
    FORECAST,
    api_client,
    get,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

PAIR_KEY = "distributor/monitor"
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "10"}


def forecast_scenario() -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = 8
    scenario["forecasts"] = [FORECAST | {"periods_ahead": 3}]
    scenario["random_disruptions"] = [
        {
            "name": "surge",
            "kind": "demand_shock",
            "target": ["monitor"],
            "chance": "0.3000",
            "duration": 2,
            "factor": "2.0000",
        }
    ]
    return scenario


def manifest_with_range() -> dict[str, Any]:
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = {"min": "30.000", "max": "50.000"}
    return manifest


def responses_of_run(
    decisions: list[dict[str, Any]],
) -> tuple[list[Any], dict[str, Any]]:
    with api_client() as client:
        run = start_run(client, manifest_with_range(), forecast_scenario())
        responses: list[Any] = [run, get(client, f"/runs/{run['id']}/observation")[1]]
        for period in range(1, 9):
            responses.append(submit(client, run["id"], period, decisions)[1])
            responses.append(get(client, f"/runs/{run['id']}/periods")[1])
        _, world = get(client, f"/runs/{run['id']}/world")
    return responses, world


def observations(responses: list[Any]) -> list[dict[str, Any]]:
    return [response for response in responses if "forecasts" in response]


def forecasts_in(document: object, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(document, dict):
        for key, value in cast(dict[str, object], document).items():
            if key == "forecasts" and isinstance(value, dict):
                for seen in cast(dict[str, list[dict[str, Any]]], value).values():
                    found.extend(seen)
            else:
                forecasts_in(value, found)
    if isinstance(document, list):
        for item in cast(list[object], document):
            forecasts_in(item, found)
    return found


def observed_forecasts(periods_ahead: int) -> list[list[dict[str, Any]]]:
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["forecasts"] = [FORECAST | {"periods_ahead": periods_ahead}]
    shown: list[list[dict[str, Any]]] = []
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario, seed=0)
        observation = get(client, f"/runs/{run['id']}/observation")[1]
        for period in range(1, 11):
            shown.append(observation["forecasts"][PAIR_KEY])
            observation = submit(client, run["id"], period, [])[1]
    return shown


def test_two_runs_with_other_decisions_show_the_same_forecasts():
    first, _ = responses_of_run([])
    second, _ = responses_of_run([BUY])

    assert [seen["forecasts"] for seen in observations(first)] == [
        seen["forecasts"] for seen in observations(second)
    ]


def test_every_shown_forecast_is_the_one_in_the_world_and_none_comes_early():
    responses, world = responses_of_run([])

    shown = observations(responses)
    assert [seen["period"] for seen in shown] == list(range(1, 9))
    for seen in shown:
        made = seen["period"]
        row = world["forecasts"][PAIR_KEY][made - 1]
        assert seen["forecasts"][PAIR_KEY] == [
            {"period": made + ahead, "quantity": quantity}
            for ahead, quantity in enumerate(row, start=1)
            if quantity is not None
        ]
    latest = 0
    for response in responses:
        if "forecasts" in response:
            latest = max(latest, response["period"] + 3)
        for forecast in forecasts_in(response, []):
            assert forecast["period"] <= min(latest, 8)


def test_a_forecast_of_no_demand_with_an_error_below_minus_1_is_shown_as_0():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["forecasts"] = [FORECAST | {"noise": "1.0000", "noise_growth": "0.5000"}]
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=6)
        submit(client, run["id"], 1, [])
        observation = submit(client, run["id"], 2, [])[1]

    # The forecasts made in period 3 have the errors -0.7144 and -1.1007, and
    # 0 * (1 - 1.1007) is 0.
    assert observation["period"] == 3
    shown = observation["forecasts"][PAIR_KEY]
    assert [(seen["period"], str(seen["quantity"])) for seen in shown] == [
        (4, "0"),
        (5, "0"),
    ]


def test_two_scenarios_differing_in_periods_ahead_show_the_same_near_forecasts():
    four, two = observed_forecasts(4), observed_forecasts(2)

    for period, (far, near) in enumerate(zip(four, two, strict=True), start=1):
        assert [seen for seen in far if seen["period"] <= period + 2] == near
