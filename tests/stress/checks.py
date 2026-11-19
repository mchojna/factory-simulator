import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from factories import COST_KINDS

type JsonObject = dict[str, Any]


# One played run: its identifier, result, periods and the number of its solves stopped
# at the time limit.
@dataclass(frozen=True, slots=True, kw_only=True)
class Play:
    run_id: str
    result: JsonObject
    periods: list[JsonObject]
    solves_at_time_limit: int


def closing_of(period: JsonObject) -> JsonObject:
    return next(step for step in period["steps"] if step["step"] == "close_period")


def total(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0))


# One message per check a finished run fails, in the order of the checks.
def violations_of_run(
    agent: str,
    description: JsonObject,
    result: JsonObject,
    periods: list[JsonObject],
) -> list[str]:
    violations: list[str] = []
    horizon = description["scenario"]["horizon"]
    if result["periods"] != horizon:
        violations.append(f"ended after period {result['periods']} of {horizon}")
    profit = Decimal(result["profit"])
    terms = result["terms"]
    formula = (
        terms["revenue"]
        - total([terms[kind] for kind in COST_KINDS])
        + terms["interest_earned"]
        + terms["salvage"]
    )
    if profit != formula:
        violations.append(
            f"profit {profit} is not revenue less costs plus interest earned and "
            f"salvage {formula}"
        )
    last = closing_of(periods[-1])
    profit_so_far = last["measures"]["total"]["profit_so_far"]
    if profit_so_far + terms["salvage"] != profit:
        violations.append(
            f"profit so far {profit_so_far} plus salvage {terms['salvage']} is not "
            f"the profit {profit}"
        )
    ledger = total(
        [entry["amount"] for period in periods for entry in period["ledger"]]
    )
    change = result["cash_at_end"] - result["cash_at_start"]
    if ledger != change:
        violations.append(f"ledger sums to {ledger}, cash changed by {change}")
    violations.extend(customer_violations(result, last["state"]))
    violations.extend(supplier_violations(description, result, last["state"]))
    violations.extend(item_violations(description, result, last["state"]))
    rejected = result["measures"]["total"]["decisions_rejected"]
    if agent != "no_decisions" and rejected != 0:
        violations.append(f"decisions rejected: {rejected}")
    return violations


# Units ordered by customers are shipped, lost or still open at the last close.
def customer_violations(result: JsonObject, state: JsonObject) -> list[str]:
    measures = result["measures"]["total"]
    ordered = measures["units_ordered"]
    shipped = measures["units_shipped"]
    lost = measures["units_lost"]
    open_units = total(
        [order["quantity"] - order["shipped"] for order in state["customer_orders"]]
    )
    if ordered == shipped + lost + open_units:
        return []
    return [
        f"customer units do not balance: ordered {ordered}, shipped {shipped}, "
        f"lost {lost}, open {open_units}"
    ]


# The sum of a field over the supplier orders of one supplier and material.
def units_of(orders: list[JsonObject], key: str, name: str) -> Decimal:
    return total(
        [
            order[name]
            for order in orders
            if f"{order['supplier']}/{order['material']}" == key
        ]
    )


# Per supplier and material, units ordered, the starting orders included, are
# accepted, rejected, lost, cancelled or still open at the last close.
def supplier_violations(
    description: JsonObject, result: JsonObject, state: JsonObject
) -> list[str]:
    violations: list[str] = []
    starting: list[JsonObject] = (
        description["scenario"]["start"].get("supplier_orders") or []
    )
    for key, measures in result["measures"]["suppliers"].items():
        ordered = measures["units_ordered_from_suppliers"] + units_of(
            starting, key, "quantity"
        )
        accepted = measures["units_accepted"]
        rejected = measures["units_rejected_at_inspection"]
        lost = measures["units_lost_in_delivery"]
        cancelled = measures["units_cancelled"]
        open_units = units_of(state["supplier_orders"], key, "open_quantity")
        if ordered != accepted + rejected + lost + cancelled + open_units:
            violations.append(
                f"supplier units do not balance: ordered {ordered}, accepted "
                f"{accepted}, rejected {rejected}, lost {lost}, cancelled "
                f"{cancelled}, open {open_units}"
            )
    return violations


# The units of an item a measure counts under every key of a kind, summed over the
# objects named `<object>/<item>`.
def units_by_item(result: JsonObject, kind: str, name: str) -> dict[str, Decimal]:
    units: dict[str, Decimal] = {}
    for key, measures in result["measures"].get(kind, {}).items():
        if "/" in key:
            item_id = key.split("/")[1]
            units[item_id] = units.get(item_id, Decimal(0)) + measures.get(name, 0)
    return units


# Per item, summed over the warehouses: the starting stock, the units accepted from
# suppliers and the good units of the lines equal the stock at the last close, the
# units production used, the units shipped and the units of transfers on the way.
def item_violations(
    description: JsonObject, result: JsonObject, state: JsonObject
) -> list[str]:
    units_in: dict[str, Decimal] = {}
    units_out: dict[str, Decimal] = {}

    def add(units: dict[str, Decimal], item_id: str, quantity: object) -> None:
        units[item_id] = units.get(item_id, Decimal(0)) + Decimal(str(quantity))

    starting: dict[str, JsonObject] = (
        description["scenario"]["start"].get("stock") or {}
    )
    for stock in starting.values():
        for item_id, quantity in stock.items():
            add(units_in, item_id, quantity)
    for units in (
        units_by_item(result, "suppliers", "units_accepted"),
        units_by_item(result, "lines", "units_good"),
    ):
        for item_id, quantity in units.items():
            add(units_in, item_id, quantity)
    for stock in state["stock"].values():
        for item_id, quantity in stock.items():
            add(units_out, item_id, quantity)
    for item_id, quantity in units_by_item(result, "warehouses", "units_used").items():
        add(units_out, item_id, quantity)
    for item_id, measures in result["measures"].get("products", {}).items():
        add(units_out, item_id, measures.get("units_shipped", 0))
    for transfer in state["transfers"]:
        add(units_out, transfer["item"], transfer["quantity"])
    violations: list[str] = []
    for item_id in sorted(units_in.keys() | units_out.keys()):
        into = units_in.get(item_id, Decimal(0))
        out = units_out.get(item_id, Decimal(0))
        if into != out:
            violations.append(
                f"units of {item_id} do not balance: in {into}, out {out}"
            )
    return violations


# A value written as JSON with the identifier of its run left out.
def without_run(value: object, run_id: str) -> str:
    return json.dumps(value, default=str, sort_keys=True).replace(run_id, "<run>")


# The message of a second play whose periods or result differ from the first; none
# when either play has a solve stopped at the time limit.
def replay_violations(first: Play, second: Play) -> list[str]:
    if first.solves_at_time_limit or second.solves_at_time_limit:
        return []
    first_text = without_run([first.periods, first.result], first.run_id)
    second_text = without_run([second.periods, second.result], second.run_id)
    if first_text == second_text:
        return []
    return [f"second play differs from the first, run {second.run_id}"]


# The messages of every check a play fails: the checks of a finished run, and for the
# second play of a world the comparison with its first play.
def violations_of_play(
    agent: str, description: JsonObject, play: Play, first: Play | None
) -> list[str]:
    violations = violations_of_run(agent, description, play.result, play.periods)
    if first is not None:
        violations += replay_violations(first, play)
    return violations
