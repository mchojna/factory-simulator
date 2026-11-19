import platform
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import duckdb
import numpy
import pytest
from factories import (
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
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from factory_simulator import engine
from factory_simulator.api.record.models.run import Interaction, Run
from factory_simulator.api.services.runs import memory, runs

BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "40"}
SHIP = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
DECISIONS: dict[int, list[Any]] = {1: [SHIP, BUY], 2: [BUY], 3: []}
FactoryBodies = tuple[dict[str, Any], dict[str, Any]]
CHANGES = [
    (
        "UPDATE traces SET \"after\" = '{{}}'"
        " WHERE run_id = '{run}' AND period = 2 AND position = 1",
        "periods.2: replayed period differs from the record",
    ),
    (
        "DELETE FROM traces WHERE run_id = '{run}' AND period = 2 AND position = 1",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE ledger SET amount = amount + 1"
        " WHERE run_id = '{run}' AND period = 2 AND position = 1",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE periods SET state = '{{}}' WHERE run_id = '{run}' AND period = 2",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE outcomes SET accepted = NOT accepted"
        " WHERE run_id = '{run}' AND period = 2",
        "periods.2: replayed period differs from the record",
    ),
    (
        "UPDATE worlds SET world = '{{}}' WHERE run_id = '{run}'",
        "world: does not match the record",
    ),
    (
        "UPDATE runs SET numpy_version = '0.0.0' WHERE id = '{run}'",
        f"runs.numpy_version: recorded 0.0.0, running {numpy.__version__}",
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


# A lock whose first taker waits until `go` is set; later takers do not.
class HeldLock:
    def __init__(self, go: threading.Event, waiting: threading.Event) -> None:
        self.lock = threading.Lock()
        self.go = go
        self.waiting = waiting

    def __enter__(self) -> bool:
        if not self.waiting.is_set():
            self.waiting.set()
            self.go.wait()
        return self.lock.acquire()

    def __exit__(self, *_: object) -> None:
        self.lock.release()


# A lock the test holds, which counts the requests that wait for it.
class CountedLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counted = threading.Condition()
        self.waiters = 0

    def __enter__(self) -> bool:
        with self.counted:
            self.waiters += 1
            self.counted.notify_all()
        return self.lock.acquire()

    def __exit__(self, *_: object) -> None:
        self.lock.release()


def stopped_run(url: str, seed: int = 7) -> tuple[dict[str, Any], Any]:
    with api_client(url) as client:
        run = start_run(client, seed=seed)
        for period in (1, 2, 3):
            status, observation = submit(client, run["id"], period, DECISIONS[period])
            assert status == 200, observation
    return run, observation


def change_record(url: str, statement: str) -> None:
    with duckdb.connect(url.removeprefix("duckdb:///")) as connection:
        connection.execute(statement)


def every_row(url: str) -> dict[str, list[str]]:
    with duckdb.connect(url.removeprefix("duckdb:///")) as connection:
        tables = [name for (name,) in connection.execute("SHOW TABLES").fetchall()]
        return {
            table: sorted(
                map(repr, connection.execute(f"SELECT * FROM {table}").fetchall())
            )
            for table in tables
        }


def other_python(part: int) -> str:
    parts = platform.python_version().split(".")
    parts[part] = str(int(parts[part]) + 1)
    return ".".join(parts)


def test_after_a_restart_a_running_run_is_rebuilt_and_a_finished_one_answers():
    with database_file() as url:
        with api_client(url) as client:
            running = start_run(client)
            finished = start_run(client, seed=8)
            run_to_the_end(client, finished)
        with api_client(url) as client:
            observation = get(client, f"/runs/{running['id']}/observation")
            submission = submit(client, running["id"], 1, [])
            result = get(client, f"/runs/{finished['id']}/result")

    assert observation[0] == 200
    assert (submission[0], submission[1]["period"]) == (200, 2)
    assert result[0] == 200


def test_a_stopped_run_shows_the_same_observation_after_a_restart():
    with database_file() as url:
        run, before = stopped_run(url)
        with api_client(url) as client:
            _, after = get(client, f"/runs/{run['id']}/observation")
            _, described = get(client, f"/runs/{run['id']}")

    assert after == before
    assert described["period"] == 4


@pytest.mark.parametrize(("statement", "message"), CHANGES)
def test_a_changed_record_refuses_the_run_and_keeps_its_rows(
    statement: str, message: str
):
    with database_file() as url:
        with api_client(url) as client:
            other = start_run(client, seed=3)
        run, _ = stopped_run(url)
        change_record(url, statement.format(run=run["id"]))
        before = every_row(url)
        with api_client(url) as client:
            first = get(client, f"/runs/{run['id']}/observation")
            second = submit(client, run["id"], 4, [])
            read = get(client, f"/runs/{run['id']}")
            periods = get(client, f"/runs/{run['id']}/periods")
            finished = run_to_the_end(client, other)
        after = every_row(url)

    assert first == (409, {"detail": message})
    assert second == (409, {"detail": message})
    assert read == (409, {"detail": message})
    assert periods == (409, {"detail": message})
    assert finished["finished"]
    other_tables = {
        "periods",
        "events",
        "ledger",
        "outcomes",
        "measures",
        "traces",
        "results",
    }
    operational_tables = {"operation_identities", "operations", "operation_bodies"}
    for table, rows in before.items():
        if table in operational_tables:
            continue
        if table not in other_tables and table != "runs":
            assert after[table] == rows
    for table, rows in before.items():
        if table in operational_tables:
            continue
        assert [row for row in after[table] if run["id"] in row] == [
            row for row in rows if run["id"] in row
        ], table


def test_a_run_of_another_package_version_is_refused():
    with database_file() as url:
        run, _ = stopped_run(url)
        change_record(
            url, f"UPDATE runs SET package_version = '0.0.0' WHERE id = '{run['id']}'"
        )
        with api_client(url) as client:
            status, refusal = get(client, f"/runs/{run['id']}")
            running = server_of(client).version

    assert (status, refusal) == (
        409,
        {"detail": f"runs.package_version: recorded 0.0.0, running {running}"},
    )


@pytest.mark.parametrize("column", ["pydantic_version", "duckdb_version", "platform"])
def test_other_versions_and_the_platform_are_not_compared(column: str):
    with database_file() as url:
        run, before = stopped_run(url)
        change_record(
            url, f"UPDATE runs SET {column} = 'other' WHERE id = '{run['id']}'"
        )
        with api_client(url) as client:
            _, after = get(client, f"/runs/{run['id']}/observation")

    assert after == before


def test_only_the_third_part_of_the_python_version_may_differ():
    with database_file() as url:
        accepted, before = stopped_run(url)
        refused, _ = stopped_run(url)
        for run, version in ((accepted, other_python(2)), (refused, other_python(1))):
            change_record(
                url,
                f"UPDATE runs SET python_version = '{version}'"
                f" WHERE id = '{run['id']}'",
            )
        with api_client(url) as client:
            _, after = get(client, f"/runs/{accepted['id']}/observation")
            refusal = get(client, f"/runs/{refused['id']}/observation")

    assert after == before
    assert refusal == (
        409,
        {
            "detail": f"runs.python_version: recorded {other_python(1)}, "
            f"running {platform.python_version()}"
        },
    )


def test_two_first_requests_at_once_rebuild_the_run_once(
    monkeypatch: pytest.MonkeyPatch,
):
    rebuilds: list[str] = []
    rebuild = runs.rebuild_run

    def counted(server: memory.Server, session: Session, run: Run) -> memory.RunMemory:
        rebuilds.append(run.id)
        return rebuild(server, session, run)

    monkeypatch.setattr(runs, "rebuild_run", counted)
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            for period in (1, 2, 3):
                submit(client, run["id"], period, DECISIONS[period])
            _, before = get(client, f"/runs/{run['id']}")
        rebuilds.clear()
        with (
            threaded_api_client(url) as client,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            requests: list[Callable[[], tuple[int, Any]]] = [
                lambda: get(client, f"/runs/{run['id']}/observation"),
                lambda: get(client, f"/runs/{run['id']}"),
            ]
            observation, described = [
                future.result()
                for future in [executor.submit(request) for request in requests]
            ]

    assert observation[0] == 200 and observation[1]["period"] == 4
    assert described == (200, before)
    assert before["period"] == 4
    assert rebuilds == [run["id"]]


def test_after_a_restart_refusals_and_checks_go_on():
    with database_file() as url:
        run, _ = stopped_run(url)
        with api_client(url) as client:
            post(client, f"/runs/{run['id']}/checks", {"period": 1, "decisions": []})
        with api_client(url) as client:
            refusal = submit(client, run["id"], 2, [])
            _, checked = post(
                client, f"/runs/{run['id']}/checks", {"period": 4, "decisions": [BUY]}
            )
            submit(client, run["id"], 4, [BUY])
            _, periods = get(client, f"/runs/{run['id']}/periods")
            interactions = records(client, Interaction, run_id=run["id"])

    assert refusal == (409, {"detail": "period: is 2, the run is in period 4"})
    assert [(row["position"], row["kind"]) for row in interactions] == [
        (1, "check"),
        (2, "refusal"),
        (3, "check"),
    ]
    steps = {step["step"]: step for step in periods["periods"][3]["steps"]}
    assert checked["outcomes"] == steps["execute_decisions"]["outcomes"]


def test_a_finished_run_answers_its_result_after_a_restart():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            run_to_the_end(client, run)
            before = get(client, f"/runs/{run['id']}/result")
        with api_client(url) as client:
            after = get(client, f"/runs/{run['id']}/result")

    assert after == before


def test_requests_waiting_for_the_lock_of_a_run_hold_no_connection():
    with database_file() as url, threaded_api_client(url) as client:
        run = start_run(client)
        held = CountedLock()
        held.lock.acquire()
        server_of(client).locks[run["id"]] = cast(threading.Lock, held)
        body: dict[str, object] = {"period": 1, "decisions": []}
        with ThreadPoolExecutor(max_workers=20) as executor:
            sent = [
                executor.submit(post, client, f"/runs/{run['id']}/checks", body)
                for _ in range(20)
            ]
            with held.counted:
                held.counted.wait_for(lambda: held.waiters == 20)
            checked_out = cast(QueuePool, engine_of(client).pool).checkedout()
            held.lock.release()
            answers = [answer.result()[0] for answer in sent]
        kept = records(client, Interaction, run_id=run["id"])

    assert checked_out == 0
    assert answers == [200] * 20
    assert [row["position"] for row in kept] == list(range(1, 21))


def test_a_read_waiting_while_the_last_period_is_submitted_never_rebuilds_the_run():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            for period in (1, 2, 3, 4):
                status, _ = submit(client, run["id"], period, DECISIONS.get(period, []))
                assert status == 200
        with threaded_api_client(url) as client:
            server = server_of(client)
            go, waiting = threading.Event(), threading.Event()
            server.locks[run["id"]] = cast(threading.Lock, HeldLock(go, waiting))
            path = f"/runs/{run['id']}/observation"
            answers: list[tuple[int, Any]] = []
            reader = threading.Thread(target=lambda: answers.append(get(client, path)))
            reader.start()
            waiting.wait()
            status, finished = submit(client, run["id"], 5, [])
            go.set()
            reader.join()
            kept = run["id"] in server.memories

    assert (status, finished["finished"]) == (200, True)
    assert answers[0] == (409, {"detail": "run: the run is finished"})
    assert not kept


def test_a_run_read_while_its_last_period_is_submitted_answers_the_finished_run():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            for period in (1, 2, 3, 4):
                status, _ = submit(client, run["id"], period, DECISIONS.get(period, []))
                assert status == 200
        with threaded_api_client(url) as client:
            server = server_of(client)
            go, waiting = threading.Event(), threading.Event()
            server.locks[run["id"]] = cast(threading.Lock, HeldLock(go, waiting))
            path = f"/runs/{run['id']}"
            answers: list[tuple[int, Any]] = []
            reader = threading.Thread(target=lambda: answers.append(get(client, path)))
            reader.start()
            waiting.wait()
            submit(client, run["id"], 5, [])
            go.set()
            reader.join()
            kept = run["id"] in server.memories
            _, stored = get(client, path)

    status, body = answers[0]
    assert status == 200
    assert body["finished"] is True
    assert body["period"] == stored["period"]
    assert not kept


def test_after_a_restart_every_reading_route_of_a_running_run_answers_as_before():
    routes = ("", "/observation", "/periods", "/result", "/world", "/export")
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            for period in (1, 2, 3):
                submit(client, run["id"], period, DECISIONS.get(period, []))
            before = {
                route: get(client, f"/runs/{run['id']}{route}") for route in routes[:3]
            }
        with api_client(url) as client:
            after = {
                route: get(client, f"/runs/{run['id']}{route}") for route in routes
            }

    assert {route: status for route, (status, _) in after.items()} == {
        "": 200,
        "/observation": 200,
        "/periods": 200,
        "/result": 409,
        "/world": 409,
        "/export": 409,
    }
    assert {route: after[route] for route in routes[:3]} == before


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_run_stopped_and_continued_gives_the_rows_of_a_run_never_stopped(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    stop = data.draw(st.integers(0, scenario["horizon"] - 1))
    restarts = data.draw(st.integers(1, 2))
    with database_file() as url:
        with api_client(url) as client:
            never_stopped = run_with_drawn_decisions(client, factory, seed, data)
            _, periods = get(client, f"/runs/{never_stopped}/periods")
            submissions = [
                {step["step"]: step for step in period["steps"]}["make_decisions"][
                    "submission"
                ]
                for period in periods["periods"]
            ]
            expected = rows_of_run(client, never_stopped)
            stopped = start_run(client, manifest, scenario, seed)
            for submission in submissions[:stop]:
                submit(
                    client, stopped["id"], submission["period"], submission["decisions"]
                )
        for _ in range(restarts - 1):
            with api_client(url):
                pass
        with api_client(url) as client:
            _, described = get(client, f"/runs/{stopped['id']}")
            for submission in submissions[stop:]:
                submit(
                    client, stopped["id"], submission["period"], submission["decisions"]
                )
            continued = rows_of_run(client, stopped["id"])

    assert described == stopped | {"period": stop + 1, "finished": False}
    assert continued == expected


@pytest.mark.slow
def test_runs_rebuilt_at_once_after_a_restart_hold_no_connection_while_they_replay(
    monkeypatch: pytest.MonkeyPatch,
):
    with database_file() as url:
        with api_client(url) as client:
            started = [start_run(client, seed=seed) for seed in range(20)]
            for run in started:
                status, _ = submit(client, run["id"], 1, [])
                assert status == 200
        with threaded_api_client(url) as client:
            connection_pool = cast(QueuePool, engine_of(client).pool)
            counts: list[int] = []
            barrier = threading.Barrier(
                20,
                action=lambda: counts.append(connection_pool.checkedout()),
                timeout=10,
            )
            advance = engine.advance_period

            def waiting(
                state: engine.State, world: engine.World, decisions: engine.Decisions
            ) -> engine.State:
                barrier.wait()
                return advance(state, world, decisions)

            monkeypatch.setattr(engine, "advance_period", waiting)
            with ThreadPoolExecutor(max_workers=20) as executor:
                sent = [
                    executor.submit(get, client, f"/runs/{run['id']}")
                    for run in started
                ]
                answers = [answer.result()[0] for answer in sent]

    assert answers == [200] * 20
    assert counts == [0]
