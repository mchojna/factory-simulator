"""The balance checks of a finished run: profit, cash, units and rejected decisions.

Examples:
    >>> total([Decimal("1.5"), Decimal("2")])
    Decimal('3.5')
"""

from decimal import Decimal

from factory_simulator.benchmark.client import JsonObject

# The cost terms of a result, each subtracted from revenue in the profit.
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


def total(values: list[Decimal]) -> Decimal:
    """Give the sum of decimals, 0 for none.

    Args:
        values (list[Decimal]): The decimals.

    Returns:
        Decimal: Their sum.

    Examples:
        >>> total([])
        Decimal('0')
    """
    return sum(values, Decimal(0))


def violations_of_run(
    agent: str,
    description: JsonObject,
    result: JsonObject,
    periods: list[JsonObject],
) -> list[str]:
    """Give one message per check a finished run fails, in the order of the checks.

    Args:
        agent (str): The agent of the run; only `no_decisions` may have rejected
            decisions.
        description (dict[str, Any]): The description of the run.
        result (dict[str, Any]): The result of the run.
        periods (list[dict[str, Any]]): The closed periods of the run.

    Returns:
        list[str]: The failed checks: horizon, profit terms, ledger and cash, the units
            of customers, suppliers and items, and rejected decisions.

    Examples:
        >>> zero = Decimal(0)
        >>> state = {"customer_orders": [], "supplier_orders": [], "stock": {}}
        >>> close = {
        ...     "step": "close_period",
        ...     "measures": {"total": {"profit_so_far": zero}},
        ...     "state": {**state, "transfers": []},
        ... }
        >>> totals = ["units_ordered", "units_shipped", "units_lost"]
        >>> result = {
        ...     "periods": 1,
        ...     "profit": zero,
        ...     "terms": dict.fromkeys(
        ...         [*COST_KINDS, "revenue", "interest_earned", "salvage"], zero
        ...     ),
        ...     "cash_at_start": zero,
        ...     "cash_at_end": zero,
        ...     "measures": {
        ...         "total": {**dict.fromkeys(totals, zero), "decisions_rejected": 2},
        ...         "suppliers": {},
        ...     },
        ... }
        >>> description = {"scenario": {"horizon": 1, "start": {}}}
        >>> periods = [{"ledger": [], "steps": [close]}]
        >>> violations_of_run("coordinated", description, result, periods)
        ['decisions rejected: 2']
    """
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
    last = _closing_of(periods[-1])
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
    violations.extend(_customer_violations(result, last["state"]))
    violations.extend(_supplier_violations(description, result, last["state"]))
    violations.extend(_item_violations(description, result, last["state"]))
    rejected = result["measures"]["total"]["decisions_rejected"]
    if agent != "no_decisions" and rejected != 0:
        violations.append(f"decisions rejected: {rejected}")
    return violations


def _closing_of(period: JsonObject) -> JsonObject:
    """Give the close step of a period.

    Args:
        period (dict[str, Any]): The closed period.

    Returns:
        dict[str, Any]: Its `close_period` step.
    """
    return next(step for step in period["steps"] if step["step"] == "close_period")


def _customer_violations(result: JsonObject, state: JsonObject) -> list[str]:
    """Give the message when ordered units are not shipped, lost or still open.

    Args:
        result (dict[str, Any]): The result of the run.
        state (dict[str, Any]): The state at the last close.

    Returns:
        list[str]: One message when the customer units do not balance, else none.
    """
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


def _units_of(orders: list[JsonObject], key: str, name: str) -> Decimal:
    """Give the sum of a field over the supplier orders of one supplier and material.

    Args:
        orders (list[dict[str, Any]]): The supplier orders.
        key (str): The `<supplier>/<material>` key.
        name (str): The summed field.

    Returns:
        Decimal: The sum.
    """
    return total(
        [
            order[name]
            for order in orders
            if f"{order['supplier']}/{order['material']}" == key
        ]
    )


def _supplier_violations(
    description: JsonObject, result: JsonObject, state: JsonObject
) -> list[str]:
    """Give the messages of suppliers whose ordered units do not balance.

    Per supplier and material, the units ordered, the starting orders included, are
    accepted, rejected, lost, cancelled or still open at the last close.

    Args:
        description (dict[str, Any]): The description of the run.
        result (dict[str, Any]): The result of the run.
        state (dict[str, Any]): The state at the last close.

    Returns:
        list[str]: One message per supplier and material that does not balance.
    """
    violations: list[str] = []
    starting: list[JsonObject] = (
        description["scenario"]["start"].get("supplier_orders") or []
    )
    for key, measures in result["measures"]["suppliers"].items():
        ordered = measures["units_ordered_from_suppliers"] + _units_of(
            starting, key, "quantity"
        )
        accepted = measures["units_accepted"]
        rejected = measures["units_rejected_at_inspection"]
        lost = measures["units_lost_in_delivery"]
        cancelled = measures["units_cancelled"]
        open_units = _units_of(state["supplier_orders"], key, "open_quantity")
        if ordered != accepted + rejected + lost + cancelled + open_units:
            violations.append(
                f"supplier units do not balance: ordered {ordered}, accepted "
                f"{accepted}, rejected {rejected}, lost {lost}, cancelled "
                f"{cancelled}, open {open_units}"
            )
    return violations


def _units_by_item(result: JsonObject, kind: str, name: str) -> dict[str, Decimal]:
    """Give the units of each item a measure counts under the keys of a kind.

    Args:
        result (dict[str, Any]): The result of the run.
        kind (str): The kind of the measure keys, such as `suppliers`.
        name (str): The measure.

    Returns:
        dict[str, Decimal]: The units by item, summed over the `<object>/<item>` keys.
    """
    units: dict[str, Decimal] = {}
    for key, measures in result["measures"].get(kind, {}).items():
        if "/" in key:
            item_id = key.split("/")[1]
            units[item_id] = units.get(item_id, Decimal(0)) + measures.get(name, 0)
    return units


def _item_violations(
    description: JsonObject, result: JsonObject, state: JsonObject
) -> list[str]:
    """Give the messages of items whose units do not balance over the warehouses.

    The starting stock, the units accepted from suppliers and the good units of the
    lines equal the stock at the last close, the units production used, the units
    shipped and the units of transfers on the way.

    Args:
        description (dict[str, Any]): The description of the run.
        result (dict[str, Any]): The result of the run.
        state (dict[str, Any]): The state at the last close.

    Returns:
        list[str]: One message per item that does not balance.
    """
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
        _units_by_item(result, "suppliers", "units_accepted"),
        _units_by_item(result, "lines", "units_good"),
    ):
        for item_id, quantity in units.items():
            add(units_in, item_id, quantity)
    for stock in state["stock"].values():
        for item_id, quantity in stock.items():
            add(units_out, item_id, quantity)
    for item_id, quantity in _units_by_item(result, "warehouses", "units_used").items():
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
