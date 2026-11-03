"""The rows of a closed period: period, events, outcomes, ledger, measures and traces.

Examples:
    >>> world = engine.draw_world(
    ...     engine.Factory(
    ...         materials={},
    ...         components={},
    ...         products={},
    ...         suppliers={},
    ...         customers={},
    ...         lines={},
    ...         warehouses={},
    ...         cash=engine.Cash(
    ...             credit_limit=Decimal(0),
    ...             credit_interest=Decimal(0),
    ...             debit_interest=Decimal(0),
    ...             overdraft_interest=Decimal(0),
    ...         ),
    ...     ),
    ...     engine.Scenario(horizon=4),
    ...     seed=0,
    ... )
    >>> public_state(engine.build_state(world))["period"]
    0
"""

from decimal import Decimal
from typing import cast

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.run import (
    Event,
    LedgerEntry,
    Measure,
    Outcome,
    Period,
    Run,
    Trace,
)
from factory_simulator.api.record.repositories import runs, save
from factory_simulator.api.schemas.run import DecisionsCreate
from factory_simulator.api.services.runs.results import build_result
from factory_simulator.api.services.writers.observation import observation_json
from factory_simulator.api.services.writers.values import plain

# The tables a closed period writes besides the result, in the order of the record.
PERIOD_TABLES: tuple[type[Base], ...] = (
    Period,
    Event,
    LedgerEntry,
    Outcome,
    Measure,
    Trace,
)

# The values of the rows of each table of a period, by column.
type PeriodRows = dict[type[Base], list[dict[str, object]]]


def write_period(
    session: Session,
    run: Run,
    state: engine.State,
    submission: DecisionsCreate,
    world: engine.World,
) -> None:
    """Write a closed period, and the result after the last one, in one transaction.

    The run, read in the session, takes its new `period` and `finished`, which hold no
    decimal, so its other columns are not checked again.

    Args:
        session (Session): The session of the request.
        run (Run): The run, changed in place.
        state (State): The state at the close of the period.
        submission (DecisionsCreate): The validated submission of the period.
        world (World): The world of the run.

    Raises:
        ValueError: If a decimal of a row has more than 12 places, more than 26
            digits before the point in a typed column, or more than 50 digits as a
            whole decimal inside JSON.

    Examples:
        >>> from factory_simulator.api.core.json import write_json
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.manifests import create_manifest
        >>> from factory_simulator.api.services.scenarios import create_scenario
        >>> from factory_simulator.api.services.runs.memory import Server, memory_of
        >>> from factory_simulator.api.services.runs.runs import start_run
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
        >>> memory = memory_of(server, run["id"])
        >>> submission = DecisionsCreate(period=1, decisions=[])
        >>> decided = engine.Decisions(period=1)
        >>> closed = engine.advance_period(memory.state, memory.world, decided)
        >>> stored = session.get(Run, run["id"])
        >>> write_period(session, stored, closed, submission, memory.world)
        >>> stored.period
        2
    """
    period = state.period
    run.period = period if state.finished else period + 1
    run.finished = state.finished
    runs.insert_rows(session, period_rows(run.id, state, submission, world))
    if state.finished:
        save(session, build_result(session, run.id, state, world))
    session.commit()


def period_rows(
    run_id: str,
    state: engine.State,
    submission: DecisionsCreate,
    world: engine.World,
) -> PeriodRows:
    """Give the rows a closed period writes to the tables of its period.

    The tables are `periods`, `events`, `ledger`, `outcomes`, `measures` and `traces`.

    Args:
        run_id (str): The identifier of the run.
        state (State): The state at the close of the period.
        submission (DecisionsCreate): The validated submission of the period.
        world (World): The world of the run.

    Returns:
        dict[type[Base], list[dict[str, object]]]: The values of each row by column,
            table by table, each table by primary key.

    Examples:
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> state = engine.start_period(engine.build_state(world), world)
        >>> closed = engine.advance_period(state, world, engine.Decisions(period=1))
        >>> submission = DecisionsCreate(period=1, decisions=[])
        >>> rows = period_rows("r-1", closed, submission, world)
        >>> [row["period"] for row in rows[Period]]
        [1]
    """
    period = state.period
    observation = observation_json(state.observation, world.scenario.hidden)
    events: list[dict[str, object]] = [
        {
            "run_id": run_id,
            "period": period,
            "position": position,
            "step": str(event["step"]),
            "kind": str(event["kind"]),
            "reference": str(event["reference"]),
            "fields": {
                key: value
                for key, value in event.items()
                if key not in ("kind", "step", "reference")
            },
        }
        for position, event in enumerate(state.period_events, start=1)
    ]
    ledger: list[dict[str, object]] = [
        {
            "run_id": run_id,
            "period": period,
            "position": position,
            "step": entry.step,
            "kind": entry.kind,
            "amount": entry.amount,
            "cash_after": entry.cash_after,
            "reference": entry.reference,
        }
        for position, entry in enumerate(state.ledger, start=1)
    ]
    outcomes: list[dict[str, object]] = [
        {
            "run_id": run_id,
            "period": period,
            "position": position,
            "decision_id": outcome.decision_id,
            "kind": outcome.decision.kind,
            "accepted": outcome.accepted,
            "reason": outcome.reason,
            "outcome": plain(outcome),
        }
        for position, outcome in enumerate(state.outcomes, start=1)
    ]
    size = len(write_json(observation).decode())
    values = dict(state.measures) | {"observation_size": {"total": Decimal(size)}}
    measures: list[dict[str, object]] = [
        {
            "run_id": run_id,
            "period": period,
            "name": name,
            "key": key,
            "value": values[name][key],
        }
        for name in sorted(values)
        for key in sorted(values[name])
    ]
    periods: list[dict[str, object]] = [
        {
            "run_id": run_id,
            "period": period,
            "observation": observation,
            "submission": submission,
            "state": public_state(state),
            "private": private_state(state),
        }
    ]
    return {
        Period: periods,
        Event: events,
        LedgerEntry: ledger,
        Outcome: outcomes,
        Measure: measures,
        Trace: [
            {
                "run_id": run_id,
                "period": period,
                "position": position,
                "step": entry.step,
                "kind": entry.kind,
                "reference": entry.reference,
                "decision_id": entry.decision_id,
                "input": plain(entry.input),
                "outcome": plain(entry.outcome),
                "before": plain(entry.before),
                "after": plain(entry.after),
            }
            for position, entry in enumerate(state.trace, start=1)
        ],
    }


def read_period_rows(
    session: Session, run_id: str, last: int
) -> dict[type[Base], dict[int, list[dict[str, object]]]]:
    """Read the stored rows of the periods 1 to last of a run, then end the transaction.

    The rollback gives the connection back to the pool, so the caller holds no
    connection while it uses the rows.

    Args:
        session (Session): The session of the request.
        run_id (str): The identifier of the run.
        last (int): The last period.

    Returns:
        dict[type[Base], dict[int, list[dict[str, object]]]]: The rows of each table
            of a period by period, each row the value of each column by its name.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_period_rows(session, "r-1", 2)[Period]
        {}
    """
    stored = {
        table: runs.rows_by_period(session, table, run_id, last)
        for table in PERIOD_TABLES
    }
    session.rollback()
    return stored


def public_state(state: engine.State) -> dict[str, object]:
    """Give the public state at the close of a period.

    Args:
        state (State): The state.

    Returns:
        dict[str, object]: Its period, cash, receivables, stock, condition, the
            item each line is set for, customer orders, production not yet in stock,
            plans, supplier orders and transfers on the way.

    Examples:
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> public_state(engine.build_state(world))["cash"]
        Decimal('0.0000')
    """
    return {
        "period": state.period,
        "cash": state.cash,
        "receivables": plain(state.receivables),
        "stock": plain(state.stock),
        "condition": plain(state.condition),
        "set_for": plain(state.set_for),
        "customer_orders": plain(state.customer_orders),
        "production": [
            {key: value for key, value in made.items() if key != "changeover_hours"}
            for made in cast(list[dict[str, object]], plain(state.production))
        ],
        "plans": plain(state.plans),
        "supplier_orders": [supplier_order(order) for order in state.supplier_orders],
        "transfers": plain(state.transfers),
    }


def supplier_order(order: engine.SupplierOrder) -> dict[str, object]:
    """Give a supplier order as the public state shows it.

    Args:
        order (SupplierOrder): The order.

    Returns:
        dict[str, object]: Its fields without `backfill` and `cancelled`;
            `arrival` only for a starting order.

    Examples:
        >>> order = engine.SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal("30"),
        ...     open_quantity=Decimal("30"),
        ...     unit_price=Decimal("2.0000"),
        ...     express=False,
        ...     placed=1,
        ...     arrival=3,
        ... )
        >>> sorted(set(plain(order)) - set(supplier_order(order)))
        ['arrival', 'backfill', 'cancelled']
    """
    shown = cast(dict[str, object], plain(order))
    del shown["backfill"]
    del shown["cancelled"]
    if order.placed > 0:
        del shown["arrival"]
    return shown


def private_state(state: engine.State) -> dict[str, object]:
    """Give the private state at the close of a period.

    Args:
        state (State): The state.

    Returns:
        dict[str, object]: The arrival and backfill periods of every open order
            placed by a buy.

    Examples:
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> private_state(engine.build_state(world))
        {'supplier_orders': {}}
    """
    return {
        "supplier_orders": {
            order.id: {"arrival": order.arrival, "backfill": order.backfill}
            for order in state.supplier_orders
            if order.placed > 0
        }
    }
