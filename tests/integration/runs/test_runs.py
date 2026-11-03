import asyncio
import re
import threading
import unittest.mock
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
from typing import Any, cast

import httpx2 as httpx
import pytest
from factories import (
    api_client,
    assert_run_balances,
    engine_of,
    example_count,
    get,
    measures_of,
    post,
    records,
    rows_of_run,
    run_to_the_end,
    run_with_drawn_decisions,
    seeds,
    server_of,
    settings_of,
    small_factories,
    start_run,
    submit,
    threaded_api_client,
    tiny_manifest,
    tiny_scenario,
    to_engine,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from factory_simulator import engine
from factory_simulator.api.core.json import write_json
from factory_simulator.api.main import create_app
from factory_simulator.api.record import repositories
from factory_simulator.api.record.models.run import (
    Interaction,
    Measure,
    Period,
    Result,
    Run,
)
from factory_simulator.api.record.repositories import runs as run_repository
from factory_simulator.api.services.runs import runs
from factory_simulator.api.services.runs.memory import Server
from factory_simulator.api.services.writers.world import world_json
from factory_simulator.engine import MEASURE_KINDS, draw_world

FactoryBodies = tuple[dict[str, Any], dict[str, Any]]
HUGE = "1" + "0" * 4300

SHIP_LISTS = st.lists(
    st.lists(
        st.fixed_dictionaries(
            {
                "order": st.sampled_from(["order-1-1", "order-2-1", "order-0-1"]),
                "quantity": st.decimals(
                    min_value=Decimal("0.001"), max_value=50, places=3
                ),
                "warehouse": st.just("main"),
            }
        ),
        max_size=3,
    ),
    max_size=8,
)


# A lock that counts its takers and records, at each entry and exit, whether the
# server still gives it as the lock of its run.
class TracedLock:
    def __init__(self, server: Server, run_id: str) -> None:
        self.lock = threading.Lock()
        self.server = server
        self.run_id = run_id
        self.counted = threading.Condition()
        self.takers = 0
        self.trace: list[tuple[str, bool]] = []

    def __enter__(self) -> bool:
        with self.counted:
            self.takers += 1
            self.counted.notify_all()
        taken = self.lock.acquire()
        self.trace.append(("enter", self.is_the_lock_of_its_run()))
        return taken

    def __exit__(self, *_: object) -> None:
        self.trace.append(("exit", self.is_the_lock_of_its_run()))
        self.lock.release()

    def is_the_lock_of_its_run(self) -> bool:
        return cast(object, self.server.locks.get(self.run_id)) is self


async def post_async(
    client: httpx.AsyncClient, path: str, body: object
) -> tuple[int, Any]:
    response = await client.post(path, content=write_json(body))
    return response.status_code, response.json()


def test_a_run_starts_in_period_1_and_shows_its_description_and_observation():
    with api_client() as client:
        run = start_run(client)
        read = get(client, f"/runs/{run['id']}")
        observation_status, observation = get(client, f"/runs/{run['id']}/observation")

    assert set(run) == {"id", "scenario_id", "description", "period", "finished"}
    assert (run["period"], run["finished"]) == (1, False)
    assert set(run["description"]) == {"manifest", "scenario", "linear"}
    assert set(run["description"]["scenario"]) == {
        "horizon",
        "start",
        "demand_shapes",
        "forecasts",
        "random_disruptions",
        "hidden",
    }
    assert run["description"]["manifest"]["name"] == "Tiny factory"
    assert read == (200, run)
    assert observation_status == 200
    assert observation["period"] == 1
    assert observation["cash"] == Decimal("1000")
    assert [order["id"] for order in observation["customer_orders"]] == ["order-1-1"]


def test_a_seed_that_is_not_a_whole_number_from_0_is_refused():
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest())
        _, scenario = post(
            client, f"/manifests/{manifest['id']}/scenarios", tiny_scenario()
        )
        body = '{"scenario_id": "' + scenario["id"] + '", "seed": 7.0}'
        response = client.post("/api/v1/runs", content=body)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "seed: is not a whole number"},
    )


def test_seeds_7_and_text_7_give_runs_with_identical_rows():
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = {"min": "30.000", "max": "50.000"}
    with api_client() as client:
        number = start_run(client, manifest, seed=7)
        text = start_run(client, manifest, seed="7")
        run_to_the_end(client, number)
        run_to_the_end(client, text)
        number_rows = rows_of_run(client, number["id"])
        text_rows = rows_of_run(client, text["id"])

    assert number_rows == text_rows


def test_unknown_run_and_scenario_answer_404():
    with api_client() as client:
        reads = [
            get(client, f"/runs/abc{route}")
            for route in ("", "/observation", "/periods", "/result", "/world")
        ]
        submitted = submit(client, "abc", 1, [])
        started = post(client, "/runs", {"scenario_id": "xyz", "seed": 1})

    assert reads == [(404, {"detail": "run_id: unknown run abc"})] * 5
    assert submitted == (404, {"detail": "run_id: unknown run abc"})
    assert started == (404, {"detail": "scenario_id: unknown scenario xyz"})


def test_periods_hold_one_entry_per_closed_period_with_six_steps_in_order():
    with api_client() as client:
        run = start_run(client)
        last = run_to_the_end(client, run)
        status, periods = get(client, f"/runs/{run['id']}/periods")

    assert last == run | {"period": 5, "finished": True}
    assert status == 200
    period_entries = periods["periods"]
    assert [period["period"] for period in period_entries] == [1, 2, 3, 4, 5]
    for period in period_entries:
        assert [step["step"] for step in period["steps"]] == [
            "receive_deliveries",
            "apply_events",
            "build_observation",
            "make_decisions",
            "execute_decisions",
            "close_period",
        ]
    first = {step["step"]: step for step in period_entries[0]["steps"]}
    assert first["apply_events"]["events"] == [
        {
            "kind": "customer_order",
            "step": "apply_events",
            "reference": "order-1-1",
            "customer": "distributor",
            "product": "monitor",
            "quantity": Decimal("4"),
            "due": 1,
            "last": 2,
        }
    ]
    assert first["make_decisions"]["submission"] == {"period": 1, "decisions": []}
    assert [event["kind"] for event in first["close_period"]["events"]] == [
        "storage_cost",
        "storage_cost",
        "storage_cost",
        "late_penalty",
        "interest",
    ]
    assert first["close_period"]["measures"]["total"]["units_ordered"] == Decimal(4)
    assert first["build_observation"]["observation"]["period"] == 1
    assert [row["kind"] for row in period_entries[0]["ledger"]] == [
        "storage_cost",
        "storage_cost",
        "storage_cost",
        "late_penalty",
        "interest_earned",
    ]


# The order `order-1-1` of 4 monitors is due in period 1 and lasts to period 2; it
# ships in full in period 2.
def test_a_unit_shipped_one_period_late_pays_one_late_penalty():
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
    with api_client() as client:
        run = start_run(client, seed=3)
        run_to_the_end(client, run, {2: [ship]})
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    penalties = [
        (period["period"], event["amount"])
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "late_penalty" and event["reference"] == "order-1-1"
    ]
    assert penalties == [(1, Decimal(8))]
    assert result["measures"]["total"]["units_shipped_late"] == Decimal(4)
    assert result["measures"]["total"]["mean_lateness"] == Decimal(1)


def test_a_period_sent_as_text_is_accepted():
    with api_client() as client:
        run = start_run(client)
        status, observation = submit(client, run["id"], "1", [])

    assert status == 200
    assert observation["period"] == 2


def test_errors_of_a_run_answer_their_status_and_text():
    with api_client() as client:
        run = start_run(client)
        world_during = get(client, f"/runs/{run['id']}/world")
        result_during = get(client, f"/runs/{run['id']}/result")
        other_period = submit(client, run["id"], 2, [])
        run_to_the_end(client, run)
        observation_after = get(client, f"/runs/{run['id']}/observation")
        submission_after = submit(client, run["id"], 5, [])

    assert world_during == (409, {"detail": "run: the run is not finished"})
    assert result_during == (409, {"detail": "run: the run is not finished"})
    assert other_period == (409, {"detail": "period: is 2, the run is in period 1"})
    assert observation_after == (409, {"detail": "run: the run is finished"})
    assert submission_after == (409, {"detail": "run: the run is finished"})


def test_a_broken_body_to_an_unknown_or_finished_run_writes_no_interaction():
    with api_client() as client:
        unknown = client.post("/api/v1/runs/abc/decisions", content=b"{not json")
        run = start_run(client)
        run_to_the_end(client, run)
        finished = client.post(
            f"/api/v1/runs/{run['id']}/decisions", content=b"{not json"
        )
        rows = records(client, Interaction)

    assert (unknown.status_code, unknown.json()) == (
        404,
        {"detail": "run_id: unknown run abc"},
    )
    assert (finished.status_code, finished.json()) == (
        409,
        {"detail": "run: the run is finished"},
    )
    assert rows == []


def test_a_finished_run_answers_its_result_world_and_record():
    with api_client() as client:
        run = start_run(client, seed=3)
        finished = run_to_the_end(client, run)
        result = get(client, f"/runs/{run['id']}/result")
        world = get(client, f"/runs/{run['id']}/world")
        periods = records(client, Period, run_id=run["id"])
        run_rows = records(client, Run, id=run["id"])
        results = records(client, Result)
        measures = records(client, Measure)

    assert (finished["period"], finished["finished"]) == (5, True)
    assert result[0] == 200
    assert set(result[1]) == {
        "seed",
        "periods",
        "profit",
        "cash_at_start",
        "cash_at_end",
        "receivables",
        "terms",
        "measures",
    }
    assert (result[1]["seed"], result[1]["periods"]) == (3, 5)
    assert result[1]["measures"]["total"]["units_ordered"] == Decimal(20)
    assert result[1]["measures"]["total"]["units_lost"] == Decimal(20)
    factory, scenario = to_engine(tiny_manifest(), tiny_scenario())
    expected_world = write_json(world_json(draw_world(factory, scenario, 3)))
    assert world[0] == 200
    assert write_json(world[1]) == expected_world
    assert [row["private"] for row in periods] == [{"supplier_orders": {}}] * 5
    assert {key for row in periods for key in row["state"]} == {
        "period",
        "cash",
        "receivables",
        "stock",
        "condition",
        "set_for",
        "customer_orders",
        "production",
        "plans",
        "supplier_orders",
        "transfers",
    }
    assert run_rows[0]["description"] == run["description"]
    assert [row["receivables"] for row in results] == [Decimal(0)]
    assert sorted({row["period"] for row in measures}) == [1, 2, 3, 4, 5]


def test_small_amounts_are_written_as_plain_json_numbers():
    manifest = tiny_manifest()
    manifest["materials"]["chip"]["storage_cost"] = "0.0001"
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {"main": {"chip": "0.001"}}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        observation = client.get(f"/api/v1/runs/{run['id']}/observation").text
        submit(client, run["id"], 1, [])
        periods = client.get(f"/api/v1/runs/{run['id']}/periods").text

    assert '"cash":1000,' in observation
    assert '"amount":-0.0000001,' in periods
    assert re.search(r"[0-9][eE][-+]?[0-9]", observation + periods) is None


@pytest.mark.slow
def test_a_server_keeps_no_lock_of_the_runs_it_has_finished():
    with api_client() as client:
        for seed in range(10):
            run = start_run(client, seed=seed)
            post(client, f"/runs/{run['id']}/checks", {"period": 1, "decisions": []})
            run_to_the_end(client, run)
            status, forked = post(client, f"/runs/{run['id']}/forks", {"period": 3})
            assert status == 201, forked
            run_to_the_end(client, forked)
        server = server_of(client)

        assert server.memories == {}
        assert server.locks == {}
        assert server.lock_users == {}


def test_a_submission_waiting_while_the_last_period_is_submitted_shares_its_lock(
    monkeypatch: pytest.MonkeyPatch,
):
    with threaded_api_client() as client:
        run = start_run(client)
        for period in (1, 2, 3, 4):
            status, _ = submit(client, run["id"], period, [])
            assert status == 200
        server = server_of(client)
        lock = TracedLock(server, run["id"])
        server.locks[run["id"]] = cast(threading.Lock, lock)
        inside, go = threading.Event(), threading.Event()
        advance = engine.advance_period

        def held(
            state: engine.State, world: engine.World, decisions: engine.Decisions
        ) -> engine.State:
            inside.set()
            go.wait()
            return advance(state, world, decisions)

        monkeypatch.setattr(engine, "advance_period", held)
        with ThreadPoolExecutor(max_workers=2) as executor:
            last = executor.submit(submit, client, run["id"], 5, [])
            inside.wait()
            waiting = executor.submit(submit, client, run["id"], 5, [])
            with lock.counted:
                lock.counted.wait_for(lambda: lock.takers == 2)
            go.set()
            answers = [last.result(), waiting.result()]
        reclaimed = (server.locks, server.lock_users)

    assert answers[0][0] == 200 and answers[0][1]["finished"] is True
    assert answers[1] == (409, {"detail": "run: the run is finished"})
    assert lock.trace == [("enter", True), ("exit", True)] * 2
    assert reclaimed == ({}, {})


def test_two_submissions_for_one_period_give_one_accepted_and_one_refused():
    with threaded_api_client() as client:
        run = start_run(client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit, client, run["id"], 1, []) for _ in range(2)
            ]
        answers = [future.result()[0] for future in futures]
        periods = records(client, Period, run_id=run["id"])
        refusals = records(client, Interaction, run_id=run["id"])

    assert sorted(answers) == [200, 409]
    assert [row["period"] for row in periods] == [1]
    assert [row["refusal"] for row in refusals] == [
        "period: is 1, the run is in period 2"
    ]


def test_a_scenario_without_start_starts_with_no_cash_stock_or_orders():
    with api_client() as client:
        run = start_run(client, scenario={"horizon": 3})
        _, observation = get(client, f"/runs/{run['id']}/observation")

    assert observation["cash"] == 0
    assert set(observation["stock"]["main"].values()) == {Decimal(0)}
    assert [order["id"] for order in observation["customer_orders"]] == ["order-1-1"]


def test_a_refused_body_with_13_places_is_answered_422_and_recorded_as_its_text():
    tiny = Decimal("0.0000000000001")
    ship = {"kind": "ship", "order": "order-1-1", "quantity": tiny}
    bodies: list[tuple[str, dict[str, Any]]] = [
        ("decisions", {"period": 1, "decisions": [ship]}),
        ("checks", {"period": 1, "decisions": [ship]}),
        ("decisions", {"period": 1 + tiny, "decisions": []}),
    ]
    with api_client() as client:
        run = start_run(client)
        answers = [
            client.post(
                f"/api/v1/runs/{run['id']}/{route}",
                content=write_json(body),
            )
            for route, body in bodies
        ]
        rows = records(client, Interaction, run_id=run["id"])

    assert [answer.status_code for answer in answers] == [422, 422, 422]
    assert [row["submission"] for row in rows] == [
        write_json(body).decode() for _, body in bodies
    ]


@pytest.mark.parametrize(
    ("seed", "detail"),
    [
        (HUGE, "seed: has more than 50 digits"),
        (f'"{HUGE}"', "seed: is not from 0 to 2 ** 128 - 1"),
    ],
)
def test_a_seed_of_4301_digits_is_refused_with_its_path(seed: str, detail: str):
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest())
        _, scenario = post(
            client, f"/manifests/{manifest['id']}/scenarios", tiny_scenario()
        )
        body = '{"scenario_id": "' + scenario["id"] + '", "seed": ' + seed + "}"
        response = client.post("/api/v1/runs", content=body)

    assert (response.status_code, response.json()) == (422, {"detail": detail})


def test_a_period_of_4301_digits_is_refused_and_recorded():
    with api_client() as client:
        run = start_run(client)
        body = '{"period": ' + HUGE + ', "decisions": []}'
        response = client.post(f"/api/v1/runs/{run['id']}/decisions", content=body)
        rows = records(client, Interaction, run_id=run["id"])

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "period: has more than 50 digits"},
    )
    assert len(rows) == 1


def test_a_defect_answers_500_with_a_fixed_text_and_not_its_own():
    app = create_app(settings_of(None, load_examples=False))
    defect = ValueError("SELECT * FROM runs WHERE id = 'secret'")

    async def submitted() -> httpx.Response:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver/api/v1"
            ) as client:
                _, manifest = await post_async(client, "/manifests", tiny_manifest())
                path = f"/manifests/{manifest['id']}/scenarios"
                _, scenario = await post_async(client, path, tiny_scenario())
                body = {"scenario_id": scenario["id"], "seed": 7}
                _, run = await post_async(client, "/runs", body)
                with unittest.mock.patch(
                    "factory_simulator.api.record.repositories.runs.insert_rows",
                    side_effect=defect,
                ):
                    return await client.post(
                        f"/runs/{run['id']}/decisions",
                        content=write_json({"period": 1, "decisions": []}),
                    )

    response = asyncio.run(submitted())

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "server: internal error"}
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "answer"),
    [
        ("GET", "/api/v1/nothing", (404, {"detail": "route: not found"})),
        ("DELETE", "/api/v1/manifests", (405, {"detail": "route: method not allowed"})),
    ],
)
def test_a_request_to_no_route_answers_the_one_error_body(
    method: str, path: str, answer: tuple[int, dict[str, str]]
):
    with api_client() as client:
        response = client.request(method, path)

    assert (response.status_code, response.json()) == answer


@pytest.mark.parametrize("seed", [0, 2**53 + 1, 2**128 - 1])
def test_a_seed_is_stored_as_text_and_answered_as_a_whole_number(seed: int):
    with api_client() as client:
        run = start_run(client, scenario=tiny_scenario() | {"horizon": 1}, seed=seed)
        run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        [stored] = records(client, Run, id=run["id"])

    assert stored["seed"] == str(seed)
    assert result["seed"] == seed


def test_a_submission_reads_its_run_once(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    find_run = run_repository.find_run

    def counted(session: Session, run_id: str) -> Run | None:
        calls.append(run_id)
        return find_run(session, run_id)

    with api_client() as client:
        run = start_run(client)
        monkeypatch.setattr(run_repository, "find_run", counted)
        status, _ = submit(client, run["id"], 1, [])

    assert status == 200
    assert calls == [run["id"]]


def test_a_submission_checks_no_column_of_its_run_again(
    monkeypatch: pytest.MonkeyPatch,
):
    columns: list[str] = []
    recorded_value = repositories.recorded_value

    def counted(column: str, value: object) -> object:
        columns.append(column)
        return recorded_value(column, value)

    with api_client() as client:
        run = start_run(client)
        monkeypatch.setattr(repositories, "recorded_value", counted)
        status, observation = submit(client, run["id"], 1, [])
        _, stored = get(client, f"/runs/{run['id']}")

    assert (status, observation["period"], stored["period"]) == (200, 2, 2)
    assert [column for column in columns if column.startswith("runs.")] == []


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, SHIP_LISTS)
def test_a_run_in_the_server_threads_equals_a_run_in_the_test_thread(
    factory: FactoryBodies, seed: int, ships: list[list[dict[str, Any]]]
):
    decisions = {
        period: [{"kind": "ship"} | ship for ship in period_ships]
        for period, period_ships in enumerate(ships, start=1)
    }
    with api_client() as client:
        through_client = start_run(client, *factory, seed)
        run_to_the_end(client, through_client, decisions)
        server = server_of(client)
        with localcontext(prec=28), Session(engine_of(client)) as session:
            in_thread: Any = runs.start_run(
                server,
                session,
                write_json(
                    {"scenario_id": through_client["scenario_id"], "seed": seed}
                ),
            )
            period = in_thread["period"]
            answer: Any = in_thread
            while not answer.get("finished", False):
                body = {"period": period, "decisions": decisions.get(period, [])}
                answer = runs.submit_decisions(
                    server, session, in_thread["id"], write_json(body)
                )
                period += 1
        client_rows = rows_of_run(client, through_client["id"])
        thread_rows = rows_of_run(client, in_thread["id"])

    assert thread_rows == client_rows


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_the_profit_the_result_and_the_space_of_a_run_follow_its_rows(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    with api_client() as client:
        run_id = run_with_drawn_decisions(client, factory, seed, data)
        _, result = get(client, f"/runs/{run_id}/result")
        _, periods = get(client, f"/runs/{run_id}/periods")
        rows = records(client, Measure, run_id=run_id)

    assert_run_balances(periods, result)
    last = periods["periods"][-1]["steps"][-1]
    assert result["cash_at_end"] == last["state"]["cash"]
    assert result["cash_at_start"] == Decimal(factory[1]["start"]["cash"])
    assert result["profit"] == (
        result["cash_at_end"]
        - result["cash_at_start"]
        + result["receivables"]
        + result["terms"]["salvage"]
    )
    whole = measures_of(rows, len(periods["periods"]))
    sums: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        if MEASURE_KINDS.get(row["name"], "flow") == "flow":
            pair = (row["name"], row["key"])
            sums[pair] = sums.get(pair, Decimal(0)) + row["value"]
    for (name, full_key), value in sums.items():
        group, _, key = full_key.partition(".")
        place = whole.setdefault(group, {})
        if key:
            place = place.setdefault(key, {})
        place[name] = value
    assert result["measures"] == whole
    for period in periods["periods"]:
        warehouses = period["steps"][-1]["measures"]["warehouses"]
        for warehouse_id in factory[0]["warehouses"]:
            items = [
                values["stock_space"]
                for key, values in warehouses.items()
                if key.startswith(f"{warehouse_id}/")
            ]
            assert warehouses[warehouse_id]["space_used"] == sum(items, Decimal(0))


def test_a_pool_timeout_answers_503(monkeypatch: pytest.MonkeyPatch):
    def timed_out(*_: object) -> object:
        raise PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")

    monkeypatch.setattr(runs, "read_run", timed_out)
    with api_client() as client:
        answer = get(client, "/runs/r-1")

    assert answer == (503, {"detail": "database: no connection was free within 30 s"})


@pytest.mark.parametrize(
    ("route", "function"),
    [
        ("decisions", "advance_period"),
        ("decisions", "start_period"),
        ("checks", "build_outcomes"),
    ],
)
def test_a_submission_and_a_check_hold_no_connection_while_the_engine_runs(
    route: str, function: str, monkeypatch: pytest.MonkeyPatch
):
    with api_client() as client:
        run = start_run(client)
        connection_pool = cast(QueuePool, engine_of(client).pool)
        counts: list[int] = []
        original = getattr(engine, function)

        def counted(*arguments: object) -> object:
            counts.append(connection_pool.checkedout())
            return original(*arguments)

        monkeypatch.setattr(engine, function, counted)
        status, answer = post(
            client, f"/runs/{run['id']}/{route}", {"period": 1, "decisions": []}
        )

    assert status == 200, answer
    assert counts == [0]


# 15 boards in periods 1 and 2 take 2 * 15 * 2 = 60 chips and 2 * 1.5 = 3 hours of
# 5 * 10 = 50. Wear leaves condition 1, 0.987, 0.97413, 0.9643887 and 0.954744813 in
# periods 1 to 5: 10 + 9.87 + 9.741 + 9.643 + 9.547 hours.
def test_the_result_holds_the_inputs_used_and_the_hours_of_a_line():
    boards = {
        period: [
            {"kind": "produce", "line": "line-1", "item": "board", "quantity": "15"}
        ]
        for period in (1, 2)
    }
    with api_client() as client:
        run = start_run(client, tiny_manifest(), tiny_scenario(), seed=5)
        run_to_the_end(client, run, boards)
        _, result = get(client, f"/runs/{run['id']}/result")

    measures = result["measures"]
    assert measures["warehouses"]["main/chip"]["units_used"] == Decimal(60)
    assert measures["lines"]["line-1"]["utilisation"] == Decimal("0.06")
    assert measures["lines"]["line-1"]["hours_available"] == Decimal("48.801")
