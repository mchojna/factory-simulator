from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from factories.client import app_of
from factories.coordinated import events_of, replying_provider
from fastapi.testclient import TestClient

from examples.coordinated_planning import STRATEGY
from examples.coordinated_planning.agent import (
    CoordinatedAgent,
    outcomes_by_position,
    settings_of,
)
from examples.coordinated_planning.play import start_case
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient]:
    app = app_of(f"duckdb:///{tmp_path / 'runs.duckdb'}", False)
    with TestClient(app, base_url="http://testserver/api/v1") as opened:
        yield opened


# A coordinated agent of a run whose model gives the answers in order.
def run_agent(
    client: TestClient,
    run: JsonObject,
    horizon: int,
    folder: Path,
    answers: list[object],
) -> CoordinatedAgent:
    return CoordinatedAgent(
        provider=replying_provider(answers),
        strategy=STRATEGY,
        settings=settings_of(horizon),
        check=partial(benchmark.create_check, client, str(run["id"])),
        folder=folder,
    )


def test_a_feasible_plan_takes_3_calls_and_no_repair(
    client: TestClient, tmp_path: Path
):
    run, horizon = start_case(client, "A3")
    agent = run_agent(client, run, horizon, tmp_path, [[], [], []])
    observation = benchmark.read(client, f"/runs/{run['id']}/observation")

    assert agent(run["description"], observation) == []
    assert agent.calls == 3
    assert events_of(tmp_path)[-1]["filter_used"] is False


def test_a_buy_of_100_chips_gives_no_chips_to_a_production_of_50_boards(
    client: TestClient, tmp_path: Path
):
    run, horizon = start_case(client, "A3")
    run_id = str(run["id"])
    observation = benchmark.read(client, f"/runs/{run_id}/observation")
    buy = {
        "kind": "buy",
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": 100,
        "warehouse": "main",
    }
    plan = [buy, {"kind": "produce", "line": "line-1", "item": "board", "quantity": 50}]

    positions = outcomes_by_position(
        1, plan, benchmark.create_check(client, run_id, 1, plan)
    )
    agent = run_agent(client, run, horizon, tmp_path, [[], [], plan, plan, plan])

    assert positions[0]["accepted"] is True
    assert positions[1]["accepted"] is False
    assert agent(run["description"], observation) == [buy]
    assert benchmark.read(client, f"/runs/{run_id}/observation") == observation


def test_an_earlier_scheduled_production_names_no_decision_of_the_plan(
    client: TestClient, tmp_path: Path
):
    run, horizon = start_case(client, "A3")
    run_id = str(run["id"])
    scheduled = {
        "kind": "produce",
        "line": "line-1",
        "item": "board",
        "quantity": 1,
        "start": 2,
    }
    benchmark.send(
        client,
        "POST",
        f"/runs/{run_id}/decisions",
        {"period": 1, "decisions": [scheduled]},
    )
    observation = benchmark.read(client, f"/runs/{run_id}/observation")
    outcomes = benchmark.create_check(client, run_id, 2, [])
    agent = run_agent(client, run, horizon, tmp_path, [[], [], []])

    assert observation["plans"]
    assert outcomes[0]["decision_id"] == "1-1"
    assert outcomes[0]["accepted"]
    assert agent(run["description"], observation) == []
    assert agent.calls == 3
