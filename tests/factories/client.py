import asyncio
import functools
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import combinations, permutations
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import strategies as st
from starlette.types import Message, Scope

from factories.bodies import (
    FactoryBodies,
    draw_world_of_bodies,
    tiny_manifest,
    tiny_scenario,
)
from factories.strategies import observed_decision_lists
from factory_simulator.api.core.config import Settings
from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.main import create_app
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import Agent, JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.models.outputs import (
    IntegerSolve,
    LinearSolve,
    Solution,
)
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions
from factory_simulator.benchmark.optimizers.reference import (
    customer_orders_of,
    reference_optimizer,
)
from factory_simulator.benchmark.program import decisions as decisions_module
from factory_simulator.benchmark.program.decisions import Optimizer, position_of
from factory_simulator.benchmark.program.solve import TIME_LIMIT, solve_program
from factory_simulator.benchmark.program.world_source import (
    entry_path,
    parameter,
    planning_input_of,
)

# The most supplier orders open in period 1 whose every set the cancellation control
# plays: 3 orders make 7 sets beside the exact control.
CANCELLABLE_ORDER_LIMIT = 3
# The most routes whose every order the transfer order control plays: 3 routes make 6
# orders beside the exact control.
ORDERED_ROUTE_LIMIT = 3


# A client of an application that sends each request through ASGI in the event loop
# of the test thread.
class Client:
    def __init__(
        self, app: FastAPI, runner: asyncio.Runner, client: httpx.AsyncClient
    ) -> None:
        self.app = app
        self.runner = runner
        self.client = client

    def request(
        self,
        method: str,
        url: str,
        content: bytes | str | None = None,
        json: object = None,
    ) -> httpx.Response:
        sent = self.client.request(method, url, content=content, json=json)
        return self.runner.run(sent)

    def get(self, url: str) -> httpx.Response:
        return self.request("GET", url)

    def post(
        self, url: str, content: bytes | str | None = None, json: object = None
    ) -> httpx.Response:
        return self.request("POST", url, content=content, json=json)


# Send a GET of the HTTP interface to the application of a client through ASGI, in
# the event loop of the client, and give each message of the answer to `read` as the
# server sends it. `read` may raise, as a client that goes away does.
def get_message_by_message(
    client: Client, path: str, read: Callable[[Message], None]
) -> None:
    url = "/api/v1" + path
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": url,
        "raw_path": url.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        read(message)

    client.runner.run(client.app(scope, receive, send))


# The settings of an application: the database URL given, or a new database in
# memory, and whether it loads the examples.
def settings_of(database_url: str | None, load_examples: bool) -> Settings:
    url = database_url or f"duckdb:///:memory:{uuid.uuid4().hex}"
    return Settings(database_url=url, load_examples=load_examples)


# The one application of the tests of a process, with examples or without. Each test
# runs a new lifespan of it, with its own database in memory and `Server`.
@functools.cache
def shared_app(load_examples: bool) -> FastAPI:
    return create_app(settings_of(None, load_examples))


# The shared application without a database URL, otherwise a new application on it.
def app_of(database_url: str | None, load_examples: bool) -> FastAPI:
    if database_url is None:
        return shared_app(load_examples)
    return create_app(settings_of(database_url, load_examples))


# A client of an application with a database of its own, examples left out unless
# asked for; the lifespan of the application runs at its start and end.
@contextmanager
def api_client(
    database_url: str | None = None, load_examples: bool = False
) -> Generator[Client]:
    app = app_of(database_url, load_examples)
    with asyncio.Runner() as runner:
        lifespan = app.router.lifespan_context(app)
        runner.run(lifespan.__aenter__())
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        try:
            yield Client(app, runner, client)
        finally:
            runner.run(client.aclose())
            runner.run(lifespan.__aexit__(None, None, None))


# A test client whose requests may come from several threads at once.
@contextmanager
def threaded_api_client(
    database_url: str | None = None, load_examples: bool = False
) -> Generator[TestClient]:
    app = app_of(database_url, load_examples)
    with TestClient(app) as client:
        yield client


# A test client whose base URL is the HTTP interface, so the client of the benchmark
# calls it as it calls a running server.
@contextmanager
def benchmark_client(load_examples: bool = False) -> Generator[TestClient]:
    app = shared_app(load_examples)
    with TestClient(app, base_url="http://testserver/api/v1") as client:
        yield client


# A run of a seed of a scenario played with no decisions over the client of the
# benchmark, and its result.
def play_no_decisions(
    client: httpx.Client, scenario_id: str, seed: int
) -> tuple[JsonObject, JsonObject]:
    run = benchmark.start_run(client, scenario_id, seed)
    result = benchmark.play_run(client, run, no_decisions)
    return run, result


# The started run of the reference of a seed of a scenario and the reference, which
# plans with the world and the customer orders of a finished run of no decisions.
def start_reference(
    client: httpx.Client,
    scenario_id: str,
    seed: int,
    no_decisions_run_id: str,
    time_limit: float = TIME_LIMIT,
    exact: bool = False,
) -> tuple[JsonObject, Optimizer]:
    world = benchmark.read_world(client, no_decisions_run_id)
    periods = benchmark.read_periods(client, no_decisions_run_id)
    run = benchmark.start_run(client, scenario_id, seed)
    check = functools.partial(benchmark.create_check, client, run["id"])
    reference = reference_optimizer(
        check, customer_orders_of(periods), world, time_limit, exact
    )
    return run, reference


# The started run of the cancellation control of a seed of a scenario, the control,
# and the exact control it plays. In period 1 it cancels the whole open quantity of
# each named supplier order and gives the decisions of the exact control with the
# cancels after them. The exact control reads period 1 without those orders and with
# their fees paid, and its check sees the cancels, which the engine runs before every
# transfer, repair, production and buy.
def start_cancellation_control(
    client: httpx.Client,
    scenario_id: str,
    seed: int,
    no_decisions_run_id: str,
    cancelled: tuple[str, ...],
) -> tuple[JsonObject, Agent, Optimizer]:
    world = benchmark.read_world(client, no_decisions_run_id)
    periods = benchmark.read_periods(client, no_decisions_run_id)
    run = benchmark.start_run(client, scenario_id, seed)
    cancels: list[JsonObject] = []

    def check(period: int, decisions: list[JsonObject]) -> list[JsonObject]:
        outcomes = benchmark.create_check(
            client, run["id"], period, decisions + cancels
        )
        return [
            outcome for outcome in outcomes if position_of(outcome) < len(decisions)
        ]

    exact_control = reference_optimizer(
        check, customer_orders_of(periods), world, exact=True
    )

    def cancellation_control(
        description: JsonObject, observation: JsonObject
    ) -> list[JsonObject]:
        cancels.clear()
        if observation["period"] > 1:
            return exact_control(description, observation)
        kept: list[JsonObject] = []
        fees = Decimal(0)
        for order in observation["supplier_orders"]:
            if order["id"] not in cancelled:
                kept.append(order)
                continue
            quantity = Decimal(order["open_quantity"])
            cancels.append(
                {"kind": "cancel", "order": order["id"], "quantity": quantity}
            )
            path = entry_path(order["supplier"], order["material"])
            fees += quantity * parameter(f"{path}.cancellation_fee", world)
        seen = observation | {
            "cash": Decimal(observation["cash"]) - fees,
            "supplier_orders": kept,
        }
        return exact_control(description, seen) + cancels

    return run, cancellation_control, exact_control


# The started run of the transfer order control of a seed of a scenario and the
# control: the exact control whose routes run in the order given, each route the
# source and destination of a route of the world. Its program holds the space of
# every warehouse in that order of transfers, and it submits its transfers in it.
def start_transfer_order_control(
    client: httpx.Client,
    scenario_id: str,
    seed: int,
    no_decisions_run_id: str,
    order: tuple[tuple[str, str], ...],
) -> tuple[JsonObject, Optimizer]:
    world = benchmark.read_world(client, no_decisions_run_id)
    customer_orders = customer_orders_of(
        benchmark.read_periods(client, no_decisions_run_id)
    )
    run = benchmark.start_run(client, scenario_id, seed)

    def planning_source(
        description: JsonObject, observation: JsonObject
    ) -> PlanningInput:
        planning = planning_input_of(observation, customer_orders, world, description)
        routes = {(route.source, route.destination): route for route in planning.routes}
        return replace(planning, routes=tuple(routes[ends] for ends in order))

    check = functools.partial(benchmark.create_check, client, run["id"])
    control = Optimizer(planning_source=planning_source, check=check, exact=True)
    return run, control


# The source and destination of every route of a world, in the order of their text.
def routes_of_world(world: JsonObject) -> tuple[tuple[str, str], ...]:
    ends = {
        (key.split(".")[1], key.split(".")[2])
        for key in world["parameters"]
        if key.startswith("routes.")
    }
    return tuple(sorted(ends))


# The identifiers of the supplier orders open in the observation of period 1 of a run.
def opening_supplier_orders(client: httpx.Client, run_id: str) -> tuple[str, ...]:
    first = benchmark.read_periods(client, run_id)[0]
    observation = next(
        step["observation"]
        for step in first["steps"]
        if step["step"] == "build_observation"
    )
    return tuple(order["id"] for order in observation["supplier_orders"])


# The first period of the window and the solution of every program an optimizer
# solves inside it, in the order solved. It patches with its own `MonkeyPatch`, as
# `recording_program_values` does.
@contextmanager
def recording_solutions() -> Generator[list[tuple[int, Solution]]]:
    solutions: list[tuple[int, Solution]] = []

    def recorded(
        planning: PlanningInput,
        time_limit: float = TIME_LIMIT,
        exact: bool = False,
        *,
        diagnostics: list[IntegerSolve | LinearSolve] | None = None,
    ) -> Solution:
        solution = solve_program(planning, time_limit, exact, diagnostics=diagnostics)
        solutions.append((planning.first_period, solution))
        return solution

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(decisions_module, "solve_program", recorded)
        yield solutions


# The first period of the window and the value of every program an optimizer solves
# inside it, in the order solved. It patches with its own `MonkeyPatch`, so it also
# works inside a Hypothesis test, where the `monkeypatch` fixture does not.
@contextmanager
def recording_program_values() -> Generator[list[tuple[int, float | None]]]:
    values: list[tuple[int, float | None]] = []

    def recorded(
        planning: PlanningInput,
        time_limit: float = TIME_LIMIT,
        exact: bool = False,
        *,
        diagnostics: list[IntegerSolve | LinearSolve] | None = None,
    ) -> Solution:
        solution = solve_program(planning, time_limit, exact, diagnostics=diagnostics)
        values.append((planning.first_period, solution.value))
        return solution

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(decisions_module, "solve_program", recorded)
        yield values


# The quality of the reference in one world, against the exact control, the reference
# with every yes-or-no choice whole in every period, each part apart: the profit of no
# decisions; the run of the reference; the value of the program of period 1 and the
# profit of each control; what each fitted and dropped, with the quantity the
# reference lost to the fit and the changeovers it paid beyond those its programs
# count; the solves of the reference stopped at the time limit, the largest gap of its
# solves and the sum of the gaps of the solves of each control; the best set of
# supplier orders open in period 1 to cancel in full, with the profit of the
# cancellation control that cancels it, the exact control when the set is empty; and
# the best order of the routes, with the profit of the transfer order control that
# runs it, the exact control when the order is empty. `future_integrality` is how much
# the later choices from 0 to 1 raise the value of the program of period 1;
# `decimal_effects` is how much the value of the exact program exceeds the profit of
# the exact control; `policy_gap` is how much more the exact control earns in the
# engine than the reference; `cancellation_gap` is how much more the cancellation
# control earns than the exact control, what the reference loses by never cancelling;
# `transfer_order_gap` is how much more the transfer order control earns than the
# exact control, what the reference loses by running its routes in the order of their
# text.
@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceQuality:
    no_decisions_profit: Decimal
    reference_run_id: str
    program_value: float
    reference_profit: Decimal
    exact_program_value: float
    exact_profit: Decimal
    fitted: int
    dropped: int
    quantity_lost: Decimal
    extra_changeovers: int
    exact_fitted: int
    exact_dropped: int
    solves_at_time_limit: int
    largest_gap: float
    gap_sum: float
    exact_gap_sum: float
    cancelled: tuple[str, ...]
    cancellation_profit: Decimal
    transfer_order: tuple[tuple[str, str], ...]
    transfer_order_profit: Decimal

    @property
    def future_integrality(self) -> float:
        return self.program_value - self.exact_program_value

    @property
    def decimal_effects(self) -> Decimal:
        return Decimal(str(self.exact_program_value)) - self.exact_profit

    @property
    def policy_gap(self) -> Decimal:
        return self.exact_profit - self.reference_profit

    @property
    def cancellation_gap(self) -> Decimal:
        return self.cancellation_profit - self.exact_profit

    @property
    def transfer_order_gap(self) -> Decimal:
        return self.transfer_order_profit - self.exact_profit


# The quantity of its planned decisions an optimizer did not submit: what the fit took
# from each fitted decision and the whole quantity or amount of each dropped one.
def quantity_lost(optimizer: Optimizer) -> Decimal:
    fitted = sum(
        (entry["before"] - entry["after"] for entry in optimizer.fitted), Decimal(0)
    )
    dropped = sum(
        (
            entry["decision"].get("quantity", entry["decision"].get("amount", 0))
            for entry in optimizer.dropped
        ),
        Decimal(0),
    )
    return fitted + dropped


# A world of a seed played with no decisions, then by the reference, by the exact
# control, by the cancellation control of every set of the supplier orders open in
# period 1 and by the transfer order control of every other order of the routes, each
# with the world of the run of no decisions.
def reference_quality_of(
    client: httpx.Client, scenario_id: str, seed: int
) -> ReferenceQuality:
    nothing, floor = play_no_decisions(client, scenario_id, seed)
    played: dict[bool, tuple[str, float, JsonObject, Optimizer]] = {}
    for exact in (False, True):
        run, optimizer = start_reference(
            client, scenario_id, seed, nothing["id"], exact=exact
        )
        with recording_program_values() as values:
            result = benchmark.play_run(client, run, optimizer)
        value = next(value for period, value in values if period == 1)
        assert value is not None
        played[exact] = run["id"], value, result, optimizer
    run_id, value, result, reference = played[False]
    _, exact_value, exact_result, exact_control = played[True]
    orders = opening_supplier_orders(client, nothing["id"])
    if len(orders) > CANCELLABLE_ORDER_LIMIT:
        raise ValueError(
            f"the cancellation control plays at most {CANCELLABLE_ORDER_LIMIT} open "
            f"supplier orders, the world has {len(orders)}"
        )
    cancelled: tuple[str, ...] = ()
    cancellation_profit = exact_result["profit"]
    for size in range(1, len(orders) + 1):
        for chosen in combinations(orders, size):
            run, control, _ = start_cancellation_control(
                client, scenario_id, seed, nothing["id"], chosen
            )
            profit = benchmark.play_run(client, run, control)["profit"]
            if profit > cancellation_profit:
                cancelled, cancellation_profit = chosen, profit
    routes = routes_of_world(benchmark.read_world(client, nothing["id"]))
    if len(routes) > ORDERED_ROUTE_LIMIT:
        raise ValueError(
            f"the transfer order control plays at most {ORDERED_ROUTE_LIMIT} routes, "
            f"the world has {len(routes)}"
        )
    transfer_order: tuple[tuple[str, str], ...] = ()
    transfer_order_profit = exact_result["profit"]
    for order in permutations(routes):
        if order == routes:
            continue
        run, control = start_transfer_order_control(
            client, scenario_id, seed, nothing["id"], order
        )
        profit = benchmark.play_run(client, run, control)["profit"]
        if profit > transfer_order_profit:
            transfer_order, transfer_order_profit = order, profit
    return ReferenceQuality(
        no_decisions_profit=floor["profit"],
        reference_run_id=run_id,
        program_value=value,
        reference_profit=result["profit"],
        exact_program_value=exact_value,
        exact_profit=exact_result["profit"],
        fitted=len(reference.fitted),
        dropped=len(reference.dropped),
        quantity_lost=quantity_lost(reference),
        extra_changeovers=sum(
            max(0, changeovers - solve.planned_changeovers.get(line_id, 0))
            for solve in reference.solves
            for line_id, changeovers in solve.changeovers.items()
        ),
        exact_fitted=len(exact_control.fitted),
        exact_dropped=len(exact_control.dropped),
        solves_at_time_limit=sum(
            solve.stopped_at_time_limit for solve in reference.solves
        ),
        largest_gap=max((solve.gap for solve in reference.solves), default=0.0),
        gap_sum=sum(solve.gap for solve in reference.solves),
        exact_gap_sum=sum(solve.gap for solve in exact_control.solves),
        cancelled=cancelled,
        cancellation_profit=cancellation_profit,
        transfer_order=transfer_order,
        transfer_order_profit=transfer_order_profit,
    )


# Send a body as canonical JSON and read the answer with exact numbers.
def post(client: Client | TestClient, path: str, body: object) -> tuple[int, Any]:
    response = client.post("/api/v1" + path, content=write_json(body))
    return response.status_code, read_json_bytes(response.content)


# Read a route and its answer with exact numbers.
def get(client: Client | TestClient, path: str) -> tuple[int, Any]:
    response = client.get("/api/v1" + path)
    return response.status_code, read_json_bytes(response.content)


# Create a manifest and a scenario over HTTP and start a run of them.
def start_run(
    client: Client | TestClient,
    manifest: dict[str, Any] | None = None,
    scenario: dict[str, Any] | None = None,
    seed: object = 7,
) -> dict[str, Any]:
    _, created_manifest = post(client, "/manifests", manifest or tiny_manifest())
    path = f"/manifests/{created_manifest['id']}/scenarios"
    _, created_scenario = post(client, path, scenario or tiny_scenario())
    status, run = post(
        client, "/runs", {"scenario_id": created_scenario["id"], "seed": seed}
    )
    assert status == 201, run
    return run


# Submit the decisions of a period of a run.
def submit(
    client: Client | TestClient, run_id: str, period: object, decisions: list[Any]
) -> tuple[int, Any]:
    return post(
        client, f"/runs/{run_id}/decisions", {"period": period, "decisions": decisions}
    )


# Submit the decisions of every period, empty unless given, until the run ends.
def run_to_the_end(
    client: Client | TestClient,
    run: dict[str, Any],
    decisions: dict[int, list[Any]] | None = None,
) -> dict[str, Any]:
    answer: Any = run
    period = run["period"]
    while not answer.get("finished", False):
        status, answer = submit(
            client, run["id"], period, (decisions or {}).get(period, [])
        )
        assert status == 200, answer
        period += 1
    return answer


# Run the bodies of a factory over HTTP with decisions drawn from each observation.
def run_with_drawn_decisions(
    client: Client | TestClient,
    bodies: FactoryBodies,
    seed: int,
    data: st.DataObject,
) -> str:
    world = draw_world_of_bodies(*bodies, seed=seed)
    run = start_run(client, *bodies, seed)
    _, observation = get(client, f"/runs/{run['id']}/observation")
    period = 1
    while not observation.get("finished", False):
        decisions = data.draw(observed_decision_lists(world, observation))
        _, observation = submit(client, run["id"], period, decisions)
        period += 1
    return run["id"]
