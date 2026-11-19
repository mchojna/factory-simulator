"""The planning input of a limited optimizer: expected values in place of the world.

Examples:
    >>> mean_of({"min": 1, "max": 2, "cut_mean": Decimal("1.500000")})
    Decimal('1.500000')
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    localcontext,
)
from typing import Literal, cast, get_args

from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.models.inputs import (
    Arrival,
    PlanningInput,
    SupplierOrder,
    TerminalValue,
)
from factory_simulator.benchmark.program.decisions import (
    QUANTITY_EXPONENT,
    PlanningSource,
)
from factory_simulator.benchmark.program.world_source import (
    ITEM_KINDS,
    active,
    buy_options_of,
    cash_of,
    customers_of,
    delivery_of,
    entry_path,
    items_of,
    lines_of,
    orders_of,
    parameter,
    remaining_share,
    round_half_even,
    routes_of,
    state_of,
    warehouses_of,
)

LEAN_TERMINAL_VALUE_FACTOR = Decimal("1.01")
BUFFERED_TERMINAL_VALUE_FACTOR = Decimal("1.2")
# The decimal context of the engine: 50 digits, and an overflow gives Infinity.
ENGINE_CONTEXT = Context(
    prec=50, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero]
)

type Window = Literal["horizon", "lead_chain", "myopic"]
"""The window of a limited optimizer: the periods its program covers."""
type Demand = Literal["expected", "order_book"]
"""The demand of a limited optimizer: the orders its program expects."""


def mean_of(value: Decimal | int | JsonObject) -> Decimal:
    """Give the mean of a fixed value or of a range.

    Args:
        value (Decimal | int | dict[str, Any]): A number, or a range of the description
            with its `cut_mean`.

    Returns:
        Decimal: The value itself, or the `cut_mean` of the range: the mean of its
            distribution cut to its bounds.

    Examples:
        >>> mean_of(Decimal("0.5"))
        Decimal('0.5')
        >>> mean_of(
        ...     {
        ...         "distribution": "normal",
        ...         "min": 1,
        ...         "max": 9,
        ...         "mean": 4,
        ...         "sd": 1,
        ...         "cut_mean": Decimal("4.000000"),
        ...     }
        ... )
        Decimal('4.000000')
    """
    if not isinstance(value, dict):
        return Decimal(value)
    return Decimal(value["cut_mean"])


def is_number(value: object) -> bool:
    """Tell whether a value of the description is a number.

    Args:
        value (object): The value.

    Returns:
        bool: True for a `Decimal` or a whole number other than `bool`.

    Examples:
        >>> is_number(Decimal("0.5")), is_number(True), is_number("main")
        (True, False, False)
    """
    return isinstance(value, Decimal | int) and not isinstance(value, bool)


def is_range(value: object) -> bool:
    """Tell whether a value of the description is a range.

    Args:
        value (object): The value.

    Returns:
        bool: True for a mapping whose `min` and `max` are numbers.

    Examples:
        >>> is_range({"min": 1, "max": 2}), is_range({"min": {}, "max": {}})
        (True, False)
    """
    if not isinstance(value, dict):
        return False
    bounds = cast(JsonObject, value)
    return is_number(bounds.get("min")) and is_number(bounds.get("max"))


def parameters_of(value: object, path: str) -> dict[str, JsonObject]:
    """Give every number and range under a path of the manifest, as their means.

    Args:
        value (object): A part of the manifest of the description.
        path (str): Its path; empty for the whole manifest.

    Returns:
        dict[str, dict[str, Any]]: `{path: {"value": mean}}` in the shape of the
            parameters of a world.

    Examples:
        >>> parameters_of({"cash": {"credit_limit": 5, "name": None}}, "")
        {'cash.credit_limit': {'value': Decimal('5')}}
    """
    if is_number(value) or is_range(value):
        return {path: {"value": mean_of(cast(Decimal | int | JsonObject, value))}}
    if not isinstance(value, dict):
        return {}
    parameters: dict[str, JsonObject] = {}
    for key, part in cast(JsonObject, value).items():
        parameters |= parameters_of(part, f"{path}.{key}" if path else key)
    return parameters


def tier_parameters(manifest: JsonObject) -> dict[str, JsonObject]:
    """Give the price of every discount tier at its mean, by the path a world names it.

    Args:
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, dict[str, Any]]: `{"<entry>.discounts.<from>.price": {"value":
            mean}}`, the `from` with 3 places.

    Examples:
        >>> entry = {"discounts": [{"from": 100, "price": Decimal("4")}]}
        >>> tier_parameters({"suppliers": {"s": {"catalogue": {"chip": entry}}}})
        {'suppliers.s.catalogue.chip.discounts.100.000.price': {'value': Decimal('4')}}
    """
    parameters: dict[str, JsonObject] = {}
    for supplier_id, supplier in manifest["suppliers"].items():
        for material_id, entry in supplier["catalogue"].items():
            tiers = cast(list[JsonObject], entry.get("discounts") or [])
            for tier in tiers:
                from_ = Decimal(tier["from"]).quantize(QUANTITY_EXPONENT)
                path = f"{entry_path(supplier_id, material_id)}.discounts.{from_}.price"
                parameters[path] = {"value": mean_of(tier["price"])}
    return parameters


def mean_or(values: JsonObject, key: str, hidden: Decimal) -> Decimal:
    """Give the mean of a parameter, or its value without loss when it is hidden.

    Args:
        values (dict[str, Any]): The parameters of an object of the description.
        key (str): The name of the parameter.
        hidden (Decimal): The value when the description leaves it out.

    Returns:
        Decimal: The mean, or `hidden`.

    Examples:
        >>> mean_or(
        ...     {"yield": {"min": "0.9", "max": 1, "cut_mean": "0.95"}},
        ...     "yield",
        ...     Decimal(1),
        ... )
        Decimal('0.95')
        >>> mean_or({}, "yield", Decimal(1))
        Decimal('1')
    """
    if key not in values:
        return hidden
    return mean_of(values[key])


def expected_world(observation: JsonObject, description: JsonObject) -> JsonObject:
    """Give the world a limited optimizer expects, in the shape of a world.

    Args:
        observation (dict[str, Any]): The observation of the period.
        description (dict[str, Any]): The description of the run.

    Returns:
        dict[str, Any]: `parameters` at their means; a price drawn once per period at
            its value seen in the period and at its mean in every other period; every
            delivery, normal or express, punctual with the mean completeness and
            acceptance; the mean yield; in every period a breakdown of `breakdown_chance
            * breakdown_loss`; and the visible disruptions, a hidden duration lasting to
            the horizon.

    Examples:
        >>> description = {"manifest": {"suppliers": {}, "lines": {}}}
        >>> observation = {
        ...     "period": 1,
        ...     "horizon": 2,
        ...     "prices": {},
        ...     "disruptions": [
        ...         {
        ...             "kind": "capacity_cut",
        ...             "target": ["line-1"],
        ...             "start": 2,
        ...             "strength": Decimal("0.5"),
        ...         }
        ...     ],
        ... }
        >>> expected_world(observation, description)["disruptions"][0]["duration"]
        1
    """
    manifest = description["manifest"]
    horizon = observation["horizon"]
    one, zero = Decimal(1), Decimal(0)
    deliveries = {
        f"{supplier_id}/{material_id}": [
            {
                "punctual": True,
                "delay": 0,
                "completeness": mean_or(entry, "completeness", one),
                "acceptance": mean_or(entry, "acceptance", one),
            }
        ]
        * horizon
        for supplier_id, supplier in manifest["suppliers"].items()
        for material_id, entry in supplier["catalogue"].items()
    }
    yields = {
        f"{line_id}/{item_id}": [mean_or(line_item, "yield", one)] * horizon
        for line_id, line in manifest["lines"].items()
        for item_id, line_item in line["items"].items()
    }
    breakdowns = {
        line_id: [
            {
                "breaks": True,
                "loss": mean_or(line, "breakdown_chance", zero)
                * mean_or(line, "breakdown_loss", zero),
            }
        ]
        * horizon
        for line_id, line in manifest["lines"].items()
    }
    disruptions = [
        disruption
        if disruption["kind"] == "line_breakdown" or "duration" in disruption
        else disruption | {"duration": horizon - disruption["start"] + 1}
        for disruption in observation["disruptions"]
    ]
    period = observation["period"]
    prices: dict[str, list[Decimal]] = {}
    for supplier_id, entries in observation["prices"].items():
        for material_id, price in entries.items():
            entry = manifest["suppliers"][supplier_id]["catalogue"][material_id]
            mean = mean_of(entry["price"])
            prices[f"{supplier_id}/{material_id}"] = (
                [mean] * (period - 1) + [Decimal(price)] + [mean] * (horizon - period)
            )
    return {
        "parameters": parameters_of(manifest, "") | tier_parameters(manifest),
        "prices": prices,
        "deliveries": deliveries,
        "express_deliveries": deliveries,
        "yields": yields,
        "breakdowns": breakdowns,
        "disruptions": disruptions,
    }


def expected_arrival(
    supplier_id: str,
    units: Decimal,
    completeness: Decimal,
    acceptance: Decimal,
    left_open: Decimal,
    period: int,
    world: JsonObject,
) -> Arrival:
    """Give the arrival a limited optimizer expects of a part of a supplier order.

    The units that arrive are the units times the completeness and the share left by
    the outages of the supplier; the units accepted are those times the acceptance and
    the share left by its quality drops. Each is rounded half to even to 3 places.

    Args:
        supplier_id (str): The identifier of the supplier.
        units (Decimal): The units of the part.
        completeness (Decimal): The share of the units that arrives.
        acceptance (Decimal): The share of the units arrived that is accepted.
        left_open (Decimal): The units left open after the arrival.
        period (int): The period of the arrival.
        world (dict[str, Any]): The expected world.

    Returns:
        Arrival: The arrival, with its units accepted.

    Examples:
        >>> world = {"disruptions": []}
        >>> half = Decimal("0.5")
        >>> expected_arrival("s", Decimal(10), Decimal(1), half, Decimal(0), 2, world)
        Arrival(period=2, accepted=Decimal('5.000'), left_open=Decimal('0'))
    """
    arrived = round_half_even(
        units
        * completeness
        * remaining_share("supplier_outage", supplier_id, period, world),
        QUANTITY_EXPONENT,
    )
    accepted = round_half_even(
        arrived
        * acceptance
        * remaining_share("quality_drop", supplier_id, period, world),
        QUANTITY_EXPONENT,
    )
    return Arrival(period=period, accepted=accepted, left_open=left_open)


def expected_supplier_orders(
    observation: JsonObject,
    horizon: int,
    world: JsonObject,
    first_deliveries: Mapping[str, int] | None = None,
) -> tuple[SupplierOrder, ...]:
    """Give the open supplier orders with the arrival a limited optimizer expects.

    A starting order arrives in full at its `expected_arrival`. Any other order
    arrives at its `expected_arrival` plus the delay of every visible
    `transport_delay` of its supplier active in that period, with the share
    `completeness * acceptance` times the share left by the outages and quality drops
    of its arrival. Its missing part arrives after `backfill_delay` when that delay is
    above 0. An order with an observed first delivery has only its backfill left.
    An arrival moves to the next period when its period has passed.

    Args:
        observation (dict[str, Any]): The observation of the period.
        horizon (int): The last period whose arrivals are kept.
        world (dict[str, Any]): The expected world.
        first_deliveries (Mapping[str, int] | None, optional): The observed first
            delivery period of each order that has had one.

    Returns:
        tuple[SupplierOrder, ...]: The orders with their expected arrivals.

    Examples:
        >>> order = {
        ...     "supplier": "s",
        ...     "material": "m",
        ...     "warehouse": "main",
        ...     "quantity": 10,
        ...     "open_quantity": 10,
        ...     "unit_price": 1,
        ...     "placed": 0,
        ...     "expected_arrival": 1,
        ... }
        >>> observation = {"period": 1, "supplier_orders": [order]}
        >>> expected_supplier_orders(observation, 3, {})[0].arrivals
        (Arrival(period=2, accepted=Decimal('10'), left_open=Decimal('0')),)
    """
    first = observation["period"]
    delivered = first_deliveries or {}
    orders: list[SupplierOrder] = []
    for order in observation["supplier_orders"]:
        units = Decimal(order["open_quantity"])
        arrival = order["expected_arrival"]
        arrivals: list[Arrival] = []
        if order["placed"] == 0:
            arrival = max(arrival, first + 1)
            if arrival <= horizon:
                arrivals.append(
                    Arrival(period=arrival, accepted=units, left_open=Decimal(0))
                )
        else:
            supplier_id, material_id = order["supplier"], order["material"]
            delays = active("transport_delay", supplier_id, arrival, world)
            arrival += sum(int(delay["delay"]) for delay in delays)
            delivery = delivery_of(
                supplier_id, material_id, order["placed"], order["express"], world
            )
            completeness = Decimal(delivery["completeness"])
            acceptance = Decimal(delivery["acceptance"])
            path = f"{entry_path(supplier_id, material_id)}.backfill_delay"
            backfill_delay = int(parameter(path, world))
            one, zero = Decimal(1), Decimal(0)
            if order["id"] in delivered:
                arrival = max(delivered[order["id"]] + backfill_delay, first + 1)
                if arrival <= horizon:
                    arrivals.append(
                        expected_arrival(
                            supplier_id, units, one, acceptance, zero, arrival, world
                        )
                    )
            else:
                arrival = max(arrival, first + 1)
                if arrival <= horizon:
                    missing = zero
                    if backfill_delay > 0:
                        missing = units - round_half_even(
                            units * completeness, QUANTITY_EXPONENT
                        )
                    arrivals.append(
                        expected_arrival(
                            supplier_id,
                            units,
                            completeness,
                            acceptance,
                            missing,
                            arrival,
                            world,
                        )
                    )
                    backfill = arrival + backfill_delay
                    if missing > 0 and backfill <= horizon:
                        arrivals.append(
                            expected_arrival(
                                supplier_id,
                                missing,
                                one,
                                acceptance,
                                zero,
                                backfill,
                                world,
                            )
                        )
        orders.append(
            SupplierOrder(
                warehouse=order["warehouse"],
                material=order["material"],
                open_quantity=units,
                unit_price=Decimal(order["unit_price"]),
                arrivals=tuple(arrivals),
            )
        )
    return tuple(orders)


def customer_product_demand(
    customer_id: str,
    product_id: str,
    demand_samples: dict[str, dict[int, Decimal]],
    terms: JsonObject,
) -> Decimal:
    """Give the mean base demand of a customer product.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        terms (dict[str, Any]): The terms of the customer product in the description.

    Returns:
        Decimal: The mean of `demand`; with hidden demand the mean of the demand
            samples of the customer product, or 0 without one.

    Examples:
        >>> customer_product_demand(
        ...     "c", "p", {"c/p": {1: Decimal(10), 2: Decimal(0)}}, {}
        ... )
        Decimal('5')
    """
    if "demand" in terms:
        return mean_of(terms["demand"])
    samples = demand_samples.get(f"{customer_id}/{product_id}", {})
    if not samples:
        return Decimal(0)
    return sum(samples.values(), Decimal(0)) / len(samples)


def forecast_of(
    observation: JsonObject, customer_id: str, product_id: str, period: int
) -> Decimal | None:
    """Give the forecast of a customer product for a period, if the observation has one.

    Args:
        observation (dict[str, Any]): The observation of the period.
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        period (int): The period forecast.

    Returns:
        Decimal | None: The quantity forecast, or None.

    Examples:
        >>> observation = {"forecasts": {"c/p": [{"period": 2, "quantity": 6}]}}
        >>> forecast_of(observation, "c", "p", 2), forecast_of(observation, "c", "p", 3)
        (Decimal('6'), None)
    """
    for forecast in observation["forecasts"].get(f"{customer_id}/{product_id}", []):
        if forecast["period"] == period:
            return Decimal(forecast["quantity"])
    return None


def shape_factor(shape: JsonObject, period: int) -> Decimal:
    """Give the factor of one demand shape in a period, as the engine computes it.

    It computes in `ENGINE_CONTEXT`, the decimal context of the engine.

    Args:
        shape (dict[str, Any]): The demand shape of the description.
        period (int): The period.

    Returns:
        Decimal: The factor of its kind: `trend`, `season`, `step`, `ramp` or
            `s_curve`.

    Examples:
        >>> shape_factor({"kind": "trend", "rate": Decimal("0.01")}, 3)
        Decimal('1.0201')
        >>> ramp = {
        ...     "kind": "ramp",
        ...     "first": 5,
        ...     "last": 9,
        ...     "from_factor": Decimal(1),
        ...     "to_factor": Decimal(2),
        ... }
        >>> shape_factor(ramp, 7)
        Decimal('1.5')
    """
    with localcontext(ENGINE_CONTEXT):
        kind = shape["kind"]
        if kind == "trend":
            return (1 + Decimal(shape["rate"])) ** (period - 1)
        if kind == "season":
            factors = shape["factors"]
            return Decimal(
                factors[((period - 1) // shape["period_length"]) % len(factors)]
            )
        if kind == "step":
            return Decimal(shape["factor"]) if period >= shape["period"] else Decimal(1)
        low, high = Decimal(shape["from_factor"]), Decimal(shape["to_factor"])
        if kind == "ramp":
            if period <= shape["first"]:
                return low
            if period >= shape["last"]:
                return high
            share = Decimal(period - shape["first"]) / (shape["last"] - shape["first"])
            return low + (high - low) * share
        # Far before the middle the exponent overflows to Infinity, which the context of
        # the engine allows, and the factor is `from_factor`.
        exponent = (-Decimal(shape["steepness"]) * (period - shape["middle"])).exp()
        return low + (high - low) / (1 + exponent)


def is_customer_product_targeted(
    target: str | JsonObject, customer_id: str, product_id: str, manifest: JsonObject
) -> bool:
    """Tell whether the target of a demand shape names a customer product.

    Args:
        target (str | dict[str, Any]): `all`, or a mapping of `customer`, `product` or a
            kind of group to an identifier.
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        bool: True when every part of the target names the customer, the product, or
            a group either is a member of.

    Examples:
        >>> manifest = {"customers": {"c": {}}, "products": {"p": {"groups": ["new"]}}}
        >>> is_customer_product_targeted({"segment": "new"}, "c", "p", manifest)
        True
        >>> is_customer_product_targeted({"customer": "d"}, "c", "p", manifest)
        False
    """
    if isinstance(target, str):
        return True
    groups: list[str] = [
        *(manifest["customers"][customer_id].get("groups") or []),
        *(manifest["products"][product_id].get("groups") or []),
    ]
    for key, value in target.items():
        if key == "customer":
            named = value == customer_id
        elif key == "product":
            named = value == product_id
        else:
            named = value in groups
        if not named:
            return False
    return True


def demand_factor(
    customer_id: str,
    product_id: str,
    period: int,
    description: JsonObject,
    world: JsonObject,
) -> Decimal:
    """Give the factor of demand shapes and visible shocks on a customer product.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        period (int): The period.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Returns:
        Decimal: The product of the factors, 1 when none acts.

    Examples:
        >>> description = {"manifest": {}, "scenario": {"demand_shapes": []}}
        >>> shock = {
        ...     "kind": "demand_shock",
        ...     "target": ["p"],
        ...     "start": 1,
        ...     "duration": 1,
        ...     "factor": Decimal("0.5"),
        ... }
        >>> demand_factor("c", "p", 1, description, {"disruptions": [shock]})
        Decimal('0.5')
    """
    manifest = description["manifest"]
    factor = Decimal(1)
    for shape in description["scenario"]["demand_shapes"]:
        if is_customer_product_targeted(
            shape["target"], customer_id, product_id, manifest
        ):
            factor *= shape_factor(shape, period)
    for shock in active("demand_shock", product_id, period, world):
        factor *= Decimal(shock["factor"])
    return factor


def add_demand_samples(
    demand_samples: dict[str, dict[int, Decimal]],
    observation: JsonObject,
    description: JsonObject,
    world: JsonObject,
) -> None:
    """Add the demand sample of every customer product in the period of an observation.

    The sample of a customer product is the quantity of its orders that arrive in the
    period, 0 without one, divided by the factor of its demand shapes and visible
    demand shocks there. A customer product whose factor is 0 gets no sample.

    Args:
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product, `<customer>/<product>`, by period, changed in place.
        observation (dict[str, Any]): The observation of the period.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Examples:
        >>> description = {
        ...     "manifest": {"customers": {"c": {"products": {"p": {}}}}},
        ...     "scenario": {"demand_shapes": []},
        ... }
        >>> samples = {}
        >>> observation = {"period": 3, "customer_orders": []}
        >>> add_demand_samples(samples, observation, description, {"disruptions": []})
        >>> samples
        {'c/p': {3: Decimal('0')}}
    """
    period = observation["period"]
    for customer_id, customer in description["manifest"]["customers"].items():
        for product_id in customer["products"]:
            factor = demand_factor(customer_id, product_id, period, description, world)
            if factor <= 0:
                continue
            quantity = sum(
                (
                    Decimal(order["quantity"])
                    for order in observation["customer_orders"]
                    if order["customer"] == customer_id
                    and order["product"] == product_id
                    and order["arrival"] == period
                ),
                Decimal(0),
            )
            samples = demand_samples.setdefault(f"{customer_id}/{product_id}", {})
            samples[period] = quantity / factor


def expected_quantity(
    customer_id: str,
    product_id: str,
    period: int,
    demand_samples: dict[str, dict[int, Decimal]],
    description: JsonObject,
    world: JsonObject,
) -> Decimal:
    """Give the quantity of a customer product a limited optimizer expects in a period.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        period (int): The period.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Returns:
        Decimal: The mean base demand of the customer product times the factor of its
            demand shapes and visible demand shocks in the period, rounded half to even
            to 3 places.

    Examples:
        >>> terms = {"demand": Decimal(4)}
        >>> description = {
        ...     "scenario": {
        ...         "demand_shapes": [
        ...             {
        ...                 "kind": "step",
        ...                 "target": "all",
        ...                 "period": 2,
        ...                 "factor": Decimal(0),
        ...             }
        ...         ]
        ...     },
        ...     "manifest": {"customers": {"c": {"products": {"p": terms}}}},
        ... }
        >>> expected_quantity("c", "p", 2, {}, description, {"disruptions": []})
        Decimal('0.000')
    """
    terms = description["manifest"]["customers"][customer_id]["products"][product_id]
    mean = customer_product_demand(customer_id, product_id, demand_samples, terms)
    factor = demand_factor(customer_id, product_id, period, description, world)
    return round_half_even(mean * factor, QUANTITY_EXPONENT)


def expected_orders(
    observation: JsonObject,
    last: int,
    demand: Demand,
    demand_samples: dict[str, dict[int, Decimal]],
    description: JsonObject,
    world: JsonObject,
) -> list[JsonObject]:
    """Give the customer orders a limited optimizer expects after the current period.

    Args:
        observation (dict[str, Any]): The observation of the period.
        last (int): The last period of the window.
        demand (Literal["expected", "order_book"]): `expected` or `order_book`.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Returns:
        list[dict[str, Any]]: Orders in the shape of the observation, by period and
            customer product.

    Examples:
        >>> description = {"manifest": {"customers": {}}}
        >>> expected_orders({"period": 1}, 3, "expected", {}, description, {})
        []
    """
    customers = description["manifest"]["customers"]
    orders: list[JsonObject] = []
    for period in range(observation["period"] + 1, last + 1):
        count = 0
        for customer_id, customer in sorted(customers.items()):
            for product_id, terms in sorted(customer["products"].items()):
                quantity = forecast_of(observation, customer_id, product_id, period)
                if quantity is None and demand == "expected":
                    quantity = expected_quantity(
                        customer_id,
                        product_id,
                        period,
                        demand_samples,
                        description,
                        world,
                    )
                if quantity is None or quantity <= 0:
                    continue
                count += 1
                due = period + int(terms["lead_time"])
                orders.append(
                    {
                        "id": f"expected-{period}-{count}",
                        "customer": customer_id,
                        "product": product_id,
                        "quantity": quantity,
                        "shipped": 0,
                        "arrival": period,
                        "due": due,
                        "last": due + int(terms["patience"]),
                    }
                )
    return orders


def first_line(item_id: str, manifest: JsonObject) -> str | None:
    """Give the first line in identifier order that makes an item.

    Args:
        item_id (str): The identifier of the item.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        str | None: The identifier of the line, or None when no line makes it.

    Examples:
        >>> manifest = {
        ...     "lines": {"b": {"items": {"board": {}}}, "a": {"items": {"board": {}}}}
        ... }
        >>> first_line("board", manifest), first_line("chip", manifest)
        ('a', None)
    """
    for line_id, line in sorted(manifest["lines"].items()):
        if item_id in line["items"]:
            return line_id
    return None


def default_recipe(item_id: str, kind: str, manifest: JsonObject) -> JsonObject:
    """Give the inputs of the default recipe of a component or a product.

    Args:
        item_id (str): The identifier of the item.
        kind (str): `components` or `products`.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, Any]: The quantity of each input per unit; empty for an item without a
            recipe.

    Examples:
        >>> item = {"default_recipe": "standard", "recipes": {"standard": {"chip": 2}}}
        >>> default_recipe("board", "components", {"components": {"board": item}})
        {'chip': 2}
    """
    item = manifest[kind][item_id]
    if item.get("default_recipe") is None:
        return {}
    return item["recipes"][item["default_recipe"]]


def replacement_costs(world: JsonObject, manifest: JsonObject) -> dict[str, Decimal]:
    """Give what one unit of every item costs to buy or make.

    Args:
        world (dict[str, Any]): The expected world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, Decimal]: For a material its lowest catalogue price; for a made
            item `(sum of recipe quantity * cost of input + cost) / yield`, with
            its default recipe on the first line that makes it. An item without a
            supplier or a line, or with an input or yield that gives no cost, is
            left out.

    Examples:
        >>> parameters = {"suppliers.s.catalogue.chip.price": {"value": 2}}
        >>> manifest = {
        ...     "materials": {"chip": {}},
        ...     "components": {},
        ...     "products": {},
        ...     "suppliers": {"s": {"catalogue": {"chip": {}}}},
        ...     "lines": {},
        ... }
        >>> replacement_costs({"parameters": parameters}, manifest)
        {'chip': Decimal('2')}
    """
    costs: dict[str, Decimal] = {}
    for material_id in sorted(manifest["materials"]):
        prices = [
            parameter(f"{entry_path(supplier_id, material_id)}.price", world)
            for supplier_id, supplier in manifest["suppliers"].items()
            if material_id in supplier["catalogue"]
        ]
        if prices:
            costs[material_id] = min(prices)
    for kind in ("components", "products"):
        for item_id in sorted(manifest[kind]):
            line_id = first_line(item_id, manifest)
            recipe = default_recipe(item_id, kind, manifest)
            if line_id is None or any(input_id not in costs for input_id in recipe):
                continue
            share = world["yields"][f"{line_id}/{item_id}"][0]
            if share == 0:
                continue
            inputs = sum(
                (
                    Decimal(quantity) * costs[input_id]
                    for input_id, quantity in recipe.items()
                ),
                Decimal(0),
            )
            cost = parameter(f"lines.{line_id}.items.{item_id}.cost", world)
            costs[item_id] = (inputs + cost) / share
    return costs


def expected_uses(
    periods: range,
    demand_samples: dict[str, dict[int, Decimal]],
    description: JsonObject,
    world: JsonObject,
) -> dict[str, Decimal]:
    """Give the units of every item the expected demand of some periods uses.

    Args:
        periods (range): The periods whose demand counts.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Returns:
        dict[str, Decimal]: For a product the sum over its customer products and the
            periods of the expected quantity; for a component or a material the sum
            over the items whose default recipe uses it of the recipe quantity times
            their use.

    Examples:
        >>> manifest = {
        ...     "customers": {"c": {"products": {"p": {"demand": 4}}}},
        ...     "materials": {},
        ...     "components": {},
        ...     "products": {
        ...         "p": {"default_recipe": "standard", "recipes": {"standard": {}}}
        ...     },
        ... }
        >>> description = {"manifest": manifest, "scenario": {"demand_shapes": []}}
        >>> expected_uses(range(2, 4), {}, description, {"disruptions": []})
        {'p': Decimal('8.000')}
    """
    manifest = description["manifest"]
    uses = {item_id: Decimal(0) for kind in ITEM_KINDS for item_id in manifest[kind]}
    for customer_id, customer in manifest["customers"].items():
        for product_id in customer["products"]:
            for period in periods:
                uses[product_id] += expected_quantity(
                    customer_id, product_id, period, demand_samples, description, world
                )
    # Products first: a product recipe uses components, a component recipe materials.
    for kind in ("products", "components"):
        for item_id in manifest[kind]:
            for input_id, quantity in default_recipe(item_id, kind, manifest).items():
                uses[input_id] += Decimal(quantity) * uses[item_id]
    return uses


def longest_chain(world: JsonObject, manifest: JsonObject) -> int:
    """Give the longest chain of lead times from placing a buy to shipping a product.

    Args:
        world (dict[str, Any]): The expected world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        int: The largest depth of a product: a material its longest catalogue
            `lead_time`, a made item the longest `lead_time` of a line that makes
            it plus the largest depth of an input of any of its recipes.

    Examples:
        >>> parameters = {
        ...     "suppliers.s.catalogue.chip.lead_time": {"value": 2},
        ...     "lines.l.items.p.lead_time": {"value": 1},
        ... }
        >>> product = {
        ...     "default_recipe": "standard",
        ...     "recipes": {"standard": {"chip": 1}},
        ... }
        >>> manifest = {
        ...     "materials": {"chip": {}},
        ...     "components": {},
        ...     "products": {"p": product},
        ...     "suppliers": {"s": {"catalogue": {"chip": {}}}},
        ...     "lines": {"l": {"items": {"p": {}}}},
        ... }
        >>> longest_chain({"parameters": parameters}, manifest)
        3
    """
    depths: dict[str, int] = {}
    for material_id in manifest["materials"]:
        depths[material_id] = max(
            (
                int(
                    parameter(
                        f"{entry_path(supplier_id, material_id)}.lead_time", world
                    )
                )
                for supplier_id, supplier in manifest["suppliers"].items()
                if material_id in supplier["catalogue"]
            ),
            default=0,
        )
    for kind in ("components", "products"):
        for item_id, item in manifest[kind].items():
            own = max(
                (
                    int(parameter(f"lines.{line_id}.items.{item_id}.lead_time", world))
                    for line_id, line in manifest["lines"].items()
                    if item_id in line["items"]
                ),
                default=0,
            )
            recipes: dict[str, JsonObject] = item.get("recipes") or {}
            inputs = max(
                (
                    depths[input_id]
                    for recipe in recipes.values()
                    for input_id in recipe
                ),
                default=0,
            )
            depths[item_id] = own + inputs
    return max((depths[product_id] for product_id in manifest["products"]), default=0)


def terminal_values_of(
    terminal_value_factor: Decimal,
    last: int,
    horizon: int,
    demand_samples: dict[str, dict[int, Decimal]],
    description: JsonObject,
    world: JsonObject,
) -> dict[str, TerminalValue]:
    """Give the terminal value of every item with a replacement cost.

    Args:
        terminal_value_factor (Decimal): What one unit up to its expected use is
            worth, as a multiple of its replacement cost.
        last (int): The last period of the window.
        horizon (int): The horizon of the run.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        description (dict[str, Any]): The description of the run.
        world (dict[str, Any]): The expected world.

    Returns:
        dict[str, TerminalValue]: Its value, `terminal_value_factor` times its
            replacement cost, and its expected use, the use of the expected demand
            of the periods after the window, as many as the longest chain of lead
            times, cut at the horizon.

    Examples:
        >>> manifest = {
        ...     "materials": {},
        ...     "components": {},
        ...     "products": {},
        ...     "suppliers": {},
        ...     "customers": {},
        ... }
        >>> description = {"manifest": manifest, "scenario": {"demand_shapes": []}}
        >>> terminal_values_of(LEAN_TERMINAL_VALUE_FACTOR, 5, 10, {}, description, {})
        {}
    """
    manifest = description["manifest"]
    periods = range(last + 1, min(last + longest_chain(world, manifest), horizon) + 1)
    uses = expected_uses(periods, demand_samples, description, world)
    return {
        item_id: TerminalValue(
            value=terminal_value_factor * cost, expected_use=uses[item_id]
        )
        for item_id, cost in replacement_costs(world, manifest).items()
    }


def expected_planning_input(
    observation: JsonObject,
    window: Window,
    demand: Demand,
    terminal_value_factor: Decimal,
    demand_samples: dict[str, dict[int, Decimal]],
    description: JsonObject,
    first_deliveries: Mapping[str, int] | None = None,
) -> PlanningInput:
    """Give the planning input of a window from what the agent knows.

    Stock at the end of a window that ends before the horizon has a terminal value.
    When the program of the input has a buy option in its first period, or a buy
    option with a minimum quantity above 0 or discount tiers, or a line item with a
    changeover time or cost above 0, it is a mixed-integer program; otherwise a
    linear program.

    Args:
        observation (dict[str, Any]): The observation of the period.
        window (Literal["horizon", "lead_chain", "myopic"]): `horizon` for every period
            to the horizon, `lead_chain` for the longest chain of lead times plus 2, cut
            at the horizon, or `myopic` for the period of the observation only.
        demand (Literal["expected", "order_book"]): `expected` for the mean demand and
            forecasts, `order_book` for forecasts only, beside the open customer orders.
        terminal_value_factor (Decimal): What one unit at the end of the window, up
            to its expected use, is worth, as a multiple of its replacement cost.
        demand_samples (dict[str, dict[int, Decimal]]): The demand samples of
            every customer product.
        description (dict[str, Any]): The description of the run.
        first_deliveries (Mapping[str, int] | None, optional): The observed first
            delivery period of each supplier order that has had one.

    Returns:
        PlanningInput: The planning input of the window.

    Examples:
        >>> cash = {
        ...     "credit_limit": 0,
        ...     "credit_interest": 0,
        ...     "debit_interest": 0,
        ...     "overdraft_interest": 0,
        ... }
        >>> description = {
        ...     "scenario": {"start": {"cash": 0}},
        ...     "manifest": {
        ...         "materials": {},
        ...         "components": {},
        ...         "products": {},
        ...         "customers": {},
        ...         "lines": {},
        ...         "suppliers": {},
        ...         "warehouses": {},
        ...         "routes": {},
        ...         "cash": cash,
        ...     },
        ... }
        >>> observation = {
        ...     "period": 1,
        ...     "horizon": 1,
        ...     "cash": 0,
        ...     "stock": {},
        ...     "lines": {},
        ...     "production": [],
        ...     "transfers": [],
        ...     "supplier_orders": [],
        ...     "receivables": [],
        ...     "customer_orders": [],
        ...     "prices": {},
        ...     "disruptions": [],
        ... }
        >>> planning = expected_planning_input(
        ...     observation,
        ...     "lead_chain",
        ...     "expected",
        ...     LEAN_TERMINAL_VALUE_FACTOR,
        ...     {},
        ...     description,
        ... )
        >>> planning.window_end, planning.horizon
        (1, 1)
    """
    manifest = description["manifest"]
    first = observation["period"]
    horizon = observation["horizon"]
    world = expected_world(observation, description)
    last = horizon
    if window == "lead_chain":
        last = min(first + longest_chain(world, manifest) + 1, horizon)
    if window == "myopic":
        last = first
    periods = range(first, last + 1)
    terminal_values: dict[str, TerminalValue] = {}
    if last < horizon:
        terminal_values = terminal_values_of(
            terminal_value_factor, last, horizon, demand_samples, description, world
        )
    state = state_of(observation, world, manifest)
    later = expected_orders(
        observation, last, demand, demand_samples, description, world
    )
    return PlanningInput(
        first_period=first,
        window_end=last,
        horizon=horizon,
        starting_cash=Decimal(description["scenario"]["start"]["cash"]),
        items=items_of(world, manifest),
        lines=lines_of(periods, world, manifest),
        warehouses=warehouses_of(observation, world),
        routes=routes_of(world, manifest),
        customers=customers_of(world, manifest),
        cash=cash_of(world),
        state=replace(
            state,
            supplier_orders=expected_supplier_orders(
                observation, horizon, world, first_deliveries
            ),
        ),
        customer_orders=orders_of(later, observation),
        buy_options=buy_options_of(periods, horizon, world, manifest),
        terminal_values=terminal_values,
    )


def expected_planning_source(
    window: Window, demand: Demand, terminal_value_factor: Decimal
) -> PlanningSource:
    """Give the planning source of a limited optimizer, which learns demand samples.

    The source adds the demand samples of every observation it sees and gives the
    expected planning input of its window, demand and terminal value factor.

    Args:
        window (Literal["horizon", "lead_chain", "myopic"]): `horizon`, `lead_chain` or
            `myopic`.
        demand (Literal["expected", "order_book"]): `expected` or `order_book`.
        terminal_value_factor (Decimal): What one unit at the end of the window, up
            to its expected use, is worth, as a multiple of its replacement cost.

    Returns:
        Callable[[dict[str, Any], dict[str, Any]], PlanningInput]: A new source with no
            demand sample.

    Raises:
        ValueError: If the window or the demand is another value.

    Examples:
        >>> expected_planning_source("weekly", "expected", LEAN_TERMINAL_VALUE_FACTOR)
        Traceback (most recent call last):
        ...
        ValueError: window: weekly is not horizon, lead_chain or myopic
    """
    if window not in get_args(Window.__value__):
        raise ValueError(f"window: {window} is not horizon, lead_chain or myopic")
    if demand not in get_args(Demand.__value__):
        raise ValueError(f"demand: {demand} is not expected or order_book")
    demand_samples: dict[str, dict[int, Decimal]] = {}
    first_deliveries: dict[str, int] = {}

    def planning_source(
        description: JsonObject, observation: JsonObject
    ) -> PlanningInput:
        world = expected_world(observation, description)
        add_demand_samples(demand_samples, observation, description, world)
        for event in observation.get("events", []):
            if event["kind"] == "delivery" and not event["backfill"]:
                first_deliveries[event["reference"]] = observation["period"]
        return expected_planning_input(
            observation,
            window,
            demand,
            terminal_value_factor,
            demand_samples,
            description,
            first_deliveries,
        )

    return planning_source


def informed_planning_source(
    terminal_value_factor: Decimal, shown_description: JsonObject
) -> PlanningSource:
    """Give the planning source of the informed optimizer, which plans from a twin.

    The source is the source of window `lead_chain` and demand `expected` that adds
    the demand samples of every observation it sees. It builds the planning input from
    `shown_description`, the description of a twin run with nothing hidden, in place
    of the description of its run, and from the observation of its run. So it counts
    a hidden range at the `cut_mean` the twin shows; it ignores punctuality and delay,
    and plans a visible disruption without a duration to the horizon, as every
    limited optimizer does.

    Args:
        terminal_value_factor (Decimal): What one unit at the end of the window, up
            to its expected use, is worth, as a multiple of its replacement cost.
        shown_description (dict[str, Any]): The description of a run of the twin of the
            scenario, with the seed of its run.

    Returns:
        Callable[[dict[str, Any], dict[str, Any]], PlanningInput]: A new source with no
            demand sample.

    Examples:
        >>> source = informed_planning_source(LEAN_TERMINAL_VALUE_FACTOR, {})
        >>> callable(source)
        True
    """
    source = expected_planning_source("lead_chain", "expected", terminal_value_factor)

    def planning_source(
        description: JsonObject,  # noqa: ARG001
        observation: JsonObject,
    ) -> PlanningInput:
        return source(shown_description, observation)

    return planning_source
