from dataclasses import asdict
from decimal import Decimal
from typing import Any

from factory_simulator.api.core.numbers import validate
from factory_simulator.api.schemas.run import DecisionsCreate
from factory_simulator.api.services.readers.decisions import to_decisions
from factory_simulator.engine import (
    Decision,
    Decisions,
    Outcome,
    Produce,
    Ship,
    State,
    World,
    advance_period,
    build_state,
    start_period,
)


# A produce of the JSON body form, on `line-1` unless another line is given.
def produce(
    item: str, quantity: str, line: str = "line-1", **keys: object
) -> dict[str, Any]:
    return {"kind": "produce", "line": line, "item": item, "quantity": quantity} | keys


# A buy of the JSON body form, of chips from `chip-maker` unless others are given.
def buy(
    quantity: str, material: str = "chip", supplier: str = "chip-maker", **keys: object
) -> dict[str, Any]:
    return {
        "kind": "buy",
        "supplier": supplier,
        "material": material,
        "quantity": quantity,
    } | keys


# A ship of the JSON body form.
def ship(order: str, quantity: str, **keys: object) -> dict[str, Any]:
    return {"kind": "ship", "order": order, "quantity": quantity} | keys


# A transfer of the JSON body form, from `main` to `centre` unless others are given.
def transfer(
    item: str, quantity: str, source: str = "main", destination: str = "centre"
) -> dict[str, Any]:
    return {
        "kind": "transfer",
        "item": item,
        "quantity": quantity,
        "source": source,
        "destination": destination,
    }


# A cancel of a whole plan or order when no quantity is given.
def cancel(order: str, quantity: str | None = None) -> dict[str, Any]:
    if quantity is None:
        return {"kind": "cancel", "order": order}
    return {"kind": "cancel", "order": order, "quantity": quantity}


# A repair of the JSON body form, of `line-1` unless another line is given.
def repair(amount: str, line: str = "line-1") -> dict[str, Any]:
    return {"kind": "repair", "line": line, "amount": amount}


# The decisions of a period given as JSON bodies, read as the HTTP interface reads them.
def submission(period: int, decisions: list[dict[str, Any]]) -> Decisions:
    body = {"period": period, "decisions": decisions}
    return to_decisions(validate(DecisionsCreate, body))


# A decision given as a JSON body, read as an engine decision.
def engine_decision(body: dict[str, Any]) -> Decision:
    return submission(1, [body]).decisions[0]


# A produce given as a JSON body, read as an engine decision.
def produce_decision(
    item: str, quantity: str, line: str = "line-1", **keys: object
) -> Produce:
    decision = engine_decision(produce(item, quantity, line, **keys))
    assert isinstance(decision, Produce)
    return decision


# A ship given as a JSON body, read as an engine decision.
def ship_decision(order: str, quantity: str, **keys: object) -> Ship:
    decision = engine_decision(ship(order, quantity, **keys))
    assert isinstance(decision, Ship)
    return decision


# Execute and close the period of a state with decisions given as JSON bodies.
def decide(state: State, world: World, decisions: list[dict[str, Any]]) -> State:
    return advance_period(state, world, submission(state.period, decisions))


# The closed first period of a world given the decisions.
def first_period(world: World, decisions: list[dict[str, Any]]) -> State:
    return decide(start_period(build_state(world), world), world, decisions)


# The started state of a period, the decisions of each earlier period executed.
def started(
    world: World, period: int, decisions: dict[int, list[dict[str, Any]]]
) -> State:
    state = start_period(build_state(world), world)
    while state.period < period:
        state = decide(state, world, decisions.get(state.period, []))
        state = start_period(state, world)
    return state


# The closed state of a period, the decisions of it and of each earlier period
# executed.
def closed_period(
    world: World, period: int, decisions: dict[int, list[dict[str, Any]]]
) -> State:
    state = started(world, period, decisions)
    return decide(state, world, decisions.get(period, []))


# The fields of an outcome that are set, its decision left out.
def outcome_fields(outcome: Outcome) -> dict[str, Any]:
    fields = {key: value for key, value in asdict(outcome).items() if value is not None}
    del fields["decision"]
    return fields


# Whether each outcome of a closed state was accepted, its reason and its numbers.
def outcome_numbers(
    state: State,
) -> list[tuple[bool, str | None, Decimal | None, Decimal | None]]:
    return [
        (outcome.accepted, outcome.reason, outcome.asked, outcome.available)
        for outcome in state.outcomes
    ]


# Each outcome of a closed state with its decision identifier, its reference, its reason
# and its numbers.
def numbered_outcomes(
    state: State,
) -> list[tuple[str, bool, str | None, str | None, Decimal | None, Decimal | None]]:
    return [
        (
            outcome.decision_id,
            outcome.accepted,
            outcome.reference,
            outcome.reason,
            outcome.asked,
            outcome.available,
        )
        for outcome in state.outcomes
    ]


# Every closed period of a whole run, the decisions of each period executed.
def closed_periods(
    world: World, decisions: dict[int, list[dict[str, Any]]]
) -> list[State]:
    state = build_state(world)
    closed: list[State] = []
    while not state.finished:
        state = start_period(state, world)
        state = decide(state, world, decisions.get(state.period, []))
        closed.append(state)
    return closed
