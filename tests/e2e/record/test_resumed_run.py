from typing import Any

import pytest
from factories import (
    api_client,
    buy,
    database_file,
    get,
    produce,
    read_answer,
    rows_of_run,
    served_app,
    ship,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.core.json import write_json

HORIZON = 6
DECISIONS: dict[int, list[dict[str, Any]]] = {
    1: [ship("order-1-1", "4"), buy("40")],
    2: [produce("board", "8")],
    3: [produce("monitor", "4")],
    4: [buy("40")],
    5: [ship("order-5-1", "4")],
}


def long_scenario() -> dict[str, Any]:
    return tiny_scenario() | {"horizon": HORIZON}


def body_of(period: int) -> bytes:
    return write_json({"period": period, "decisions": DECISIONS.get(period, [])})


@pytest.mark.slow
def test_a_killed_server_lets_the_run_finish_after_it_starts_again():
    with database_file() as url:
        with served_app(url) as client:
            manifest = read_answer(
                client.post("/api/v1/manifests", content=write_json(tiny_manifest()))
            )
            scenario = read_answer(
                client.post(
                    f"/api/v1/manifests/{manifest['id']}/scenarios",
                    content=write_json(long_scenario()),
                )
            )
            start = write_json({"scenario_id": scenario["id"], "seed": 5})
            run = read_answer(client.post("/api/v1/runs", content=start))
            for period in (1, 2, 3):
                client.post(
                    f"/api/v1/runs/{run['id']}/decisions", content=body_of(period)
                )
        with served_app(url) as client:
            statuses = [
                client.post(
                    f"/api/v1/runs/{run['id']}/decisions", content=body_of(period)
                ).status_code
                for period in range(4, HORIZON + 1)
            ]
            finished = read_answer(client.get(f"/api/v1/runs/{run['id']}"))
        with api_client(url) as client:
            rows = rows_of_run(client, run["id"])
            _, result = get(client, f"/runs/{run['id']}/result")
        with api_client() as client:
            never_stopped = start_run(client, scenario=long_scenario(), seed=5)
            for period in range(1, HORIZON + 1):
                submit(client, never_stopped["id"], period, DECISIONS.get(period, []))
            expected = rows_of_run(client, never_stopped["id"])

    assert statuses == [200] * (HORIZON - 3)
    assert finished["finished"]
    assert result["periods"] == HORIZON
    assert rows == expected
