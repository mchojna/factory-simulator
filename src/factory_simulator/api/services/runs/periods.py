"""The closed periods of a run: each with its six steps and its ledger rows.

Examples:
    >>> event = {"step": "close_period", "kind": "x", "reference": "y", "fields": {}}
    >>> period_events([event])["close_period"]
    [{'kind': 'x', 'step': 'close_period', 'reference': 'y'}]
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import cast

from sqlalchemy.orm import Session

from factory_simulator.api.record.models.run import (
    Event,
    LedgerEntry,
    Measure,
    Outcome,
    Period,
)
from factory_simulator.api.services.runs.memory import Server
from factory_simulator.api.services.runs.results import nested_measures
from factory_simulator.api.services.runs.rows import read_period_rows
from factory_simulator.api.services.runs.runs import read_running_memory
from factory_simulator.api.services.runs.stored import stored_run


def read_periods(server: Server, session: Session, run_id: str) -> object:
    """Read every closed period of a run with its six steps and ledger rows.

    It reads every stored row first and ends the transaction, so building the
    answer holds no connection.

    Args:
        server (Server): The server, changed in place.
        session (Session): The session of the request.
        run_id (str): The identifier of the run.

    Returns:
        object: `{"periods": [{"period", "steps", "ledger"}, ...]}`.

    Raises:
        NotFoundError: If the run does not exist.
        ConflictError: If the run is running and its record does not rebuild it.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> read_periods(Server(version="0.1.0"), session, "r-1")
        Traceback (most recent call last):
        ...
        factory_simulator.api.core.errors.NotFoundError: run_id: unknown run r-1
    """
    run = stored_run(session, run_id)
    if not run.finished:
        read_running_memory(server, session, run_id)
    stored = read_period_rows(session, run_id, run.period)
    periods: list[object] = []
    for period, kept_periods in stored[Period].items():
        kept = kept_periods[0]
        events = period_events(stored[Event].get(period, []))
        outcomes = [row["outcome"] for row in stored[Outcome].get(period, [])]
        ledger = [
            {
                "period": period,
                "step": entry["step"],
                "kind": entry["kind"],
                "amount": entry["amount"],
                "cash_after": entry["cash_after"],
                "reference": entry["reference"],
            }
            for entry in stored[LedgerEntry].get(period, [])
        ]
        steps: list[dict[str, object]] = [
            {"step": "receive_deliveries", "events": events["receive_deliveries"]},
            {"step": "apply_events", "events": events["apply_events"]},
            {"step": "build_observation", "observation": kept["observation"]},
            {"step": "make_decisions", "submission": kept["submission"]},
            {"step": "execute_decisions", "outcomes": outcomes},
            {
                "step": "close_period",
                "events": events["close_period"],
                "state": kept["state"],
                "measures": nested_measures(
                    (
                        cast(str, measure["name"]),
                        cast(str, measure["key"]),
                        cast(Decimal | None, measure["value"]),
                    )
                    for measure in stored[Measure].get(period, [])
                ),
            },
        ]
        periods.append({"period": period, "steps": steps, "ledger": ledger})
    return {"periods": periods}


def period_events(stored: list[dict[str, object]]) -> dict[str, list[object]]:
    """Give the events of a period by the step that reported them.

    Args:
        stored (list[dict[str, object]]): The stored events of the period, in
            order, each the value of each column by its name.

    Returns:
        dict[str, list[object]]: The events of `receive_deliveries`,
            `apply_events` and `close_period`, in order.

    Examples:
        >>> event = {
        ...     "step": "apply_events",
        ...     "kind": "breakdown",
        ...     "reference": "press",
        ...     "fields": {},
        ... }
        >>> period_events([event])["apply_events"]
        [{'kind': 'breakdown', 'step': 'apply_events', 'reference': 'press'}]
    """
    events: dict[str, list[object]] = {
        "receive_deliveries": [],
        "apply_events": [],
        "close_period": [],
    }
    for event in stored:
        others = cast(Mapping[str, object], event["fields"])
        step = cast(str, event["step"])
        whole = {"kind": event["kind"], "step": step, "reference": event["reference"]}
        events.setdefault(step, []).append(whole | dict(others))
    return events
