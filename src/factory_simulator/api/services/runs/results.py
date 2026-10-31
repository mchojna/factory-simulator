"""The result of a finished run: profit, its terms and the measures of the run.

Examples:
    >>> nested_measures([("cash", "total", 1), ("stock", "warehouses.main", 2)])
    {'total': {'cash': 1}, 'warehouses': {'main': {'stock': 2}}}
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.record.models.run import Result
from factory_simulator.api.record.repositories import runs
from factory_simulator.api.services.runs.stored import finished_run

# The kind of every measure of the record; the HTTP interface adds the size of
# the observation.
MEASURE_KINDS = {**engine.MEASURE_KINDS, "observation_size": "flow"}

COST_KINDS = (
    "material_payment",
    "production_cost",
    "transport_cost",
    "storage_cost",
    "repair_cost",
    "cancellation_fee",
    "overtime_cost",
    "changeover_cost",
    "transfer_cost",
    "interest_paid",
    "late_penalty",
    "lost_sale_penalty",
)


@engine.in_decimal_context
def build_result(
    session: Session, run_id: str, state: engine.State, world: engine.World
) -> Result:
    """Build the result of a finished run: profit and each of its terms.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        state (State): The state at the end.
        world (World): The world of the run.

    Returns:
        Result: The row of the result.

    Examples:
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.manifests import create_manifest
        >>> from factory_simulator.api.services.scenarios import create_scenario
        >>> from factory_simulator.api.services.runs.memory import Server, memory_of
        >>> from factory_simulator.api.services.runs.runs import (
        ...     start_run,
        ...     submit_decisions,
        ... )
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> server = Server(version="0.1.0")
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = create_manifest(session, manifest_body)
        >>> _, scenario = create_scenario(session, manifest["id"], b'{"horizon": 3}')
        >>> body = write_json({"scenario_id": scenario["id"], "seed": 7})
        >>> run = start_run(server, session, body)
        >>> empty = b'{"period": 1, "decisions": []}'
        >>> _ = submit_decisions(server, session, run["id"], empty)
        >>> memory = memory_of(server, run["id"])
        >>> result = build_result(session, run["id"], memory.state, memory.world)
        >>> result.cash_at_end == memory.state.cash
        True
    """
    totals = runs.ledger_totals(session, run_id)
    measures = run_measures(runs.measure_rows(session, run_id))
    salvage = engine.compute_salvage(state, world)
    receivables = sum(
        (receivable.amount for receivable in state.receivables), Decimal(0)
    )
    terms: dict[str, Decimal] = {
        kind: -totals.get(kind, Decimal(0)) for kind in COST_KINDS
    }
    terms["revenue"] = cast(dict[str, Decimal], measures["total"])["revenue"]
    terms["interest_earned"] = totals.get("interest_earned", Decimal(0))
    terms["salvage"] = salvage
    cash_at_start = world.scenario.start.cash
    return Result(
        run_id=run_id,
        profit=engine.compute_profit(state, world),
        cash_at_start=cash_at_start,
        cash_at_end=state.cash,
        receivables=receivables,
        terms=terms,
        measures=measures,
    )


@engine.in_decimal_context
def run_measures(rows: list[tuple[str, str, Decimal | None]]) -> dict[str, object]:
    """Give the measures of a whole run from the rows of its periods.

    Flows are summed; levels and ratios keep their value of the last period, and a
    ratio of a period is already computed from running totals.

    Args:
        rows (list[tuple[str, str, Decimal | None]]): The name, key and value of
            every row, in period order.

    Returns:
        dict[str, object]: The measures by key, then by name.

    Examples:
        >>> revenue = [("revenue", "total", Decimal(n)) for n in (5, 7)]
        >>> cash = [("cash", "total", Decimal(n)) for n in (3, 4)]
        >>> run_measures(revenue + cash)
        {'total': {'revenue': Decimal('12'), 'cash': Decimal('4')}}
    """
    whole: dict[tuple[str, str], Decimal | None] = {}
    for name, key, value in rows:
        earlier = whole.get((name, key))
        if MEASURE_KINDS[name] == "flow" and earlier is not None and value is not None:
            value = earlier + value
        whole[(name, key)] = value
    return nested_measures((name, key, value) for (name, key), value in whole.items())


def nested_measures(
    values: Iterable[tuple[str, str, Decimal | None]],
) -> dict[str, object]:
    """Give measures grouped by the kind of key, then the object, then the name.

    Args:
        values (Iterable[tuple[str, str, Decimal | None]]): The name, key and value
            of each measure.

    Returns:
        dict[str, object]: `{"total": {name: value}, "customers": {"<customer>":
            {name: value}}, ...}`.

    Examples:
        >>> nested_measures([("cash", "total", 1), ("stock", "warehouses.main", 2)])
        {'total': {'cash': 1}, 'warehouses': {'main': {'stock': 2}}}
    """
    nested: dict[str, dict[str, Any]] = {}
    for name, key, value in values:
        group, _, member = key.partition(".")
        place = nested.setdefault(group, {})
        if member:
            place = place.setdefault(member, {})
        place[name] = value
    return dict(nested)


def read_result(session: Session, run_id: str) -> object:
    """Read the result of a finished run.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        object: `{"seed", "periods", "profit", "cash_at_start", "cash_at_end",
            "receivables", "terms", "measures"}`.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is not finished.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_result(session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = finished_run(session, run_id)
    result = cast(Result, run.result)
    return {
        "seed": int(run.seed),
        "periods": run.period,
        "profit": result.profit,
        "cash_at_start": result.cash_at_start,
        "cash_at_end": result.cash_at_end,
        "receivables": result.receivables,
        "terms": result.terms,
        "measures": result.measures,
    }
