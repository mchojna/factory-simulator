import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import duckdb
import numpy
import pytest
from factories import (
    Client,
    api_client,
    database_file,
    engine_of,
    example_count,
    get,
    post,
    records,
    rows_of_run,
    run_to_the_end,
    run_with_drawn_decisions,
    seeds,
    server_of,
    small_factories,
    start_run,
    submit,
    threaded_api_client,
)
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.pool import QueuePool

from factory_simulator import engine
from factory_simulator.api.record.models.run import Interaction, Run

HORIZON = 5
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "40"}
DECISIONS: dict[int, list[Any]] = {
    1: [{"kind": "ship", "order": "order-1-1", "quantity": "4"}, BUY],
    2: [{"kind": "produce", "line": "line-1", "item": "board", "quantity": "8"}],
    3: [{"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "4"}],
}
CHANGES = [
    (
        "UPDATE ledger SET amount = amount + 1"
        " WHERE run_id = '{run}' AND period = 2 AND position = 1",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE runs SET numpy_version = '0.0.0' WHERE id = '{run}'",
        f"runs.numpy_version: recorded 0.0.0, running {numpy.__version__}",
    ),
    (
        "UPDATE worlds SET world = '{{}}' WHERE run_id = '{run}'",
        "world: does not match the record",
    ),
    (
        "DELETE FROM periods WHERE run_id = '{run}' AND period = 2",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE periods SET submission = '{{}}' WHERE run_id = '{run}' AND period = 2",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE periods"
        " SET submission = json_merge_patch(submission, '{{\"period\": 3}}')"
        " WHERE run_id = '{run}' AND period = 2",
        "periods.2: replayed period differs from the record",
    ),
]
FactoryBodies = tuple[dict[str, Any], dict[str, Any]]


# A lock that sets `waited` when a second request comes to take it.
class WatchedLock:
    def __init__(self, waited: threading.Event) -> None:
        self.lock = threading.Lock()
        self.waited = waited
        self.takers = 0

    def __enter__(self) -> bool:
        self.takers += 1
        if self.takers > 1:
            self.waited.set()
        return self.lock.acquire()

    def __exit__(self, *_: object) -> None:
        self.lock.release()


def fork(client: Client | TestClient, run_id: str, period: object) -> tuple[int, Any]:
    return post(client, f"/runs/{run_id}/forks", {"period": period})


def finished_run(client: Client | TestClient, seed: int = 7) -> dict[str, Any]:
    run = start_run(client, seed=seed)
    run_to_the_end(client, run, DECISIONS)
    return run


def compared(rows: dict[str, list[Any]], since: int = 1) -> dict[str, list[Any]]:
    kept: dict[str, list[Any]] = {}
    for table, found in rows.items():
        if table == "interactions":
            continue
        if table == "runs":
            found = [
                {
                    key: value
                    for key, value in row.items()
                    if key not in ("forked_from", "forked_from_period")
                }
                for row in found
            ]
        kept[table] = [row for row in found if row.get("period", since) >= since]
    return kept


def test_a_fork_at_period_1_equals_a_new_run():
    with api_client() as client:
        parent = finished_run(client)
        status, forked = fork(client, parent["id"], 1)
        fresh = start_run(client, seed=7)
        fork_rows = compared(rows_of_run(client, forked["id"]))
        fresh_rows = compared(rows_of_run(client, fresh["id"]))

    assert status == 201
    assert (forked["period"], forked["finished"]) == (1, False)
    assert fork_rows == fresh_rows


def test_a_fork_at_the_horizon_replays_every_period_but_the_last():
    with api_client() as client:
        parent = finished_run(client)
        status, forked = fork(client, parent["id"], HORIZON)
        _, periods = get(client, f"/runs/{forked['id']}/periods")
        _, parent_periods = get(client, f"/runs/{parent['id']}/periods")

    assert status == 201
    assert forked["period"] == HORIZON
    assert periods["periods"] == parent_periods["periods"][: HORIZON - 1]


def test_the_forks_route_answers_in_the_order_of_its_checks():
    with api_client() as client:
        run = start_run(client)
        unfinished = fork(client, run["id"], 3)
        unfinished_broken = client.post(
            f"/api/v1/runs/{run['id']}/forks", content=b"not json"
        )
        run_to_the_end(client, run)
        not_json = client.post(f"/api/v1/runs/{run['id']}/forks", content=b"not json")
        answers = [fork(client, run["id"], period) for period in (0, HORIZON + 1, "x")]
        unknown = fork(client, "abc", 3)
        as_number = fork(client, run["id"], 3)
        as_text = fork(client, run["id"], "3")

    assert unfinished == (409, {"detail": "run: the run is not finished"})
    assert unfinished_broken.status_code == 409
    assert not_json.status_code == 422
    assert not_json.json()["detail"].startswith("body: ")
    for status, refusal in answers:
        assert status == 422
        assert refusal["detail"].startswith("period: ")
    assert unknown == (404, {"detail": "run_id: unknown run abc"})
    assert (as_number[0], as_text[0]) == (201, 201)
    assert as_number[1]["id"] != as_text[1]["id"]


def test_a_fork_given_other_decisions_finishes_with_another_result():
    other = {4: [BUY | {"quantity": "500"}]}
    with api_client() as client:
        parent = finished_run(client)
        _, forked = fork(client, parent["id"], 3)
        run_to_the_end(client, forked, other)
        fresh = start_run(client, seed=7)
        run_to_the_end(client, fresh, {1: DECISIONS[1], 2: DECISIONS[2]} | other)
        _, parent_result = get(client, f"/runs/{parent['id']}/result")
        _, fork_result = get(client, f"/runs/{forked['id']}/result")
        fork_rows = compared(rows_of_run(client, forked["id"]), since=4)
        fresh_rows = compared(rows_of_run(client, fresh["id"]), since=4)

    assert fork_result["profit"] != parent_result["profit"]
    assert fork_rows == fresh_rows


def test_a_fork_names_its_parent_and_a_fork_of_a_fork_names_its_own():
    with api_client() as client:
        parent = finished_run(client)
        before = rows_of_run(client, parent["id"])
        _, child = fork(client, parent["id"], 3)
        run_to_the_end(client, child)
        _, grandchild = fork(client, child["id"], 2)
        after = rows_of_run(client, parent["id"])
        [child_row] = records(client, Run, id=child["id"])
        [grandchild_row] = records(client, Run, id=grandchild["id"])

    assert (child_row["forked_from"], child_row["forked_from_period"]) == (
        parent["id"],
        3,
    )
    assert (grandchild_row["forked_from"], grandchild_row["forked_from_period"]) == (
        child["id"],
        2,
    )
    assert after == before


def test_two_forks_at_once_give_two_runs_that_both_finish():
    with threaded_api_client() as client:
        parent = finished_run(client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(fork, client, parent["id"], 2) for _ in range(2)]
            answers = [future.result() for future in futures]
        finished = [run_to_the_end(client, answer[1]) for answer in answers]

    assert [status for status, _ in answers] == [201, 201]
    assert answers[0][1]["id"] != answers[1][1]["id"]
    assert all(run["finished"] for run in finished)


def test_the_interactions_of_a_fork_start_empty():
    with api_client() as client:
        run = start_run(client)
        submit(client, run["id"], 2, [])
        run_to_the_end(client, run)
        _, forked = fork(client, run["id"], 3)
        parent_rows = records(client, Interaction, run_id=run["id"])
        fork_rows = records(client, Interaction, run_id=forked["id"])

    assert len(parent_rows) == 1
    assert fork_rows == []


@pytest.mark.parametrize(("statement", "message"), CHANGES)
def test_a_changed_parent_refuses_the_fork_and_writes_no_run(
    statement: str, message: str
):
    with database_file() as url:
        with api_client(url) as client:
            parent = finished_run(client)
        with duckdb.connect(url.removeprefix("duckdb:///")) as connection:
            connection.execute(statement.format(run=parent["id"]))
        with api_client(url) as client:
            answer = fork(client, parent["id"], 4)
            runs = records(client, Run)

    assert answer == (409, {"detail": message})
    assert [row["id"] for row in runs] == [parent["id"]]


def test_forks_go_on_after_a_restart():
    with database_file() as url:
        with api_client(url) as client:
            parent = finished_run(client)
            _, forked = fork(client, parent["id"], 3)
        with api_client(url) as client:
            status, answer = submit(client, forked["id"], 3, [])
            second = fork(client, parent["id"], 2)

    assert (status, answer["period"]) == (200, 4)
    assert second[0] == 201


def test_a_fork_holds_no_connection_while_it_replays(monkeypatch: pytest.MonkeyPatch):
    with database_file() as url, threaded_api_client(url) as client:
        parent = finished_run(client)
        connection_pool = cast(QueuePool, engine_of(client).pool)
        counts: list[int] = []
        advance = engine.advance_period

        def counted(
            state: engine.State, world: engine.World, decisions: engine.Decisions
        ) -> engine.State:
            counts.append(connection_pool.checkedout())
            return advance(state, world, decisions)

        monkeypatch.setattr(engine, "advance_period", counted)
        status, _ = fork(client, parent["id"], 3)

    assert status == 201
    assert counts == [0, 0]


def test_the_observation_of_a_finished_run_answers_409_while_a_fork_holds_its_lock(
    monkeypatch: pytest.MonkeyPatch,
):
    with threaded_api_client() as client:
        parent = finished_run(client)
        settled = threading.Event()
        server_of(client).locks[parent["id"]] = cast(
            threading.Lock, WatchedLock(settled)
        )
        inside, go = threading.Event(), threading.Event()
        advance = engine.advance_period

        def held(
            state: engine.State, world: engine.World, decisions: engine.Decisions
        ) -> engine.State:
            inside.set()
            go.wait()
            return advance(state, world, decisions)

        monkeypatch.setattr(engine, "advance_period", held)
        answers: list[tuple[int, Any]] = []

        def read_observation() -> None:
            answers.append(get(client, f"/runs/{parent['id']}/observation"))
            settled.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            forked = executor.submit(fork, client, parent["id"], 2)
            inside.wait()
            executor.submit(read_observation)
            settled.wait()
            answered_while_held = list(answers)
            go.set()
        status, _ = forked.result()

    assert answered_while_held == [(409, {"detail": "run: the run is finished"})]
    assert status == 201


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_fork_given_the_decisions_of_its_parent_writes_its_rows(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    horizon = int(factory[1]["horizon"])
    period = data.draw(st.integers(1, horizon))
    with api_client() as client:
        parent = run_with_drawn_decisions(client, factory, seed, data)
        _, periods = get(client, f"/runs/{parent}/periods")
        status, forked = fork(client, parent, period)
        replayed = compared(rows_of_run(client, forked["id"]))
        for period_entry in periods["periods"][period - 1 :]:
            submission = {step["step"]: step for step in period_entry["steps"]}[
                "make_decisions"
            ]["submission"]
            submit(client, forked["id"], submission["period"], submission["decisions"])
        parent_rows = compared(rows_of_run(client, parent))
        fork_rows = compared(rows_of_run(client, forked["id"]))

    assert status == 201
    assert fork_rows == parent_rows
    before = {
        table: [row for row in found if row.get("period", 0) < period]
        for table, found in parent_rows.items()
        if table not in ("runs", "worlds", "results")
    }
    assert {table: replayed[table] for table in before} == before
