"""The world as a planning input: the coefficients of the program read from a world.

Examples:
    >>> world = {"parameters": {"cash.credit_limit": {"value": 5}}}
    >>> parameter("cash.credit_limit", world)
    Decimal('5')
"""

from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.models.inputs import (
    Arrival,
    BuyOption,
    Cash,
    Customer,
    CustomerOrder,
    CustomerProduct,
    Hours,
    Item,
    Line,
    LineItem,
    PlanningInput,
    Production,
    Receivable,
    Route,
    SupplierOrder,
    Tier,
    TransferOnTheWay,
    Warehouse,
    WindowStart,
)
from factory_simulator.benchmark.program.decisions import QUANTITY_EXPONENT

ITEM_KINDS = ("materials", "components", "products")
PRICE_EXPONENT = Decimal("0.0001")


def parameter(path: str, world: JsonObject) -> Decimal:
    """Give the value of a parameter of the world.

    Args:
        path (str): The key path of the parameter.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: Its value.

    Examples:
        >>> world = {"parameters": {"cash.credit_limit": {"value": 5}}}
        >>> parameter("cash.credit_limit", world)
        Decimal('5')
    """
    return Decimal(world["parameters"][path]["value"])


def parameter_or_zero(path: str, world: JsonObject) -> Decimal:
    """Give the value of a parameter that may be left out, 0 when it is.

    Args:
        path (str): The key path of the parameter.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: Its value, or 0.

    Examples:
        >>> path = "lines.line-1.items.board.changeover_cost"
        >>> parameter_or_zero(path, {"parameters": {}})
        Decimal('0')
    """
    if path not in world["parameters"]:
        return Decimal(0)
    return parameter(path, world)


def is_active(disruption: JsonObject, period: int) -> bool:
    """Tell whether a disruption of the world acts in a period.

    Args:
        disruption (dict[str, Any]): The disruption.
        period (int): The period.

    Returns:
        bool: `start <= period <= start + duration - 1`; a `line_breakdown` acts in
            its start period only.

    Examples:
        >>> is_active({"kind": "line_breakdown", "start": 3}, 3)
        True
        >>> is_active({"kind": "supplier_outage", "start": 3, "duration": 2}, 5)
        False
    """
    if disruption["kind"] == "line_breakdown":
        return period == disruption["start"]
    return (
        disruption["start"]
        <= period
        <= disruption["start"] + disruption["duration"] - 1
    )


def active(kind: str, target: str, period: int, world: JsonObject) -> list[JsonObject]:
    """Give the disruptions of a kind that act on a target in a period.

    Args:
        kind (str): The kind of disruption.
        target (str): The identifier of the target.
        period (int): The period.
        world (dict[str, Any]): The world.

    Returns:
        list[dict[str, Any]]: The disruptions.

    Examples:
        >>> world = {
        ...     "disruptions": [
        ...         {
        ...             "kind": "transport_delay",
        ...             "target": ["s"],
        ...             "start": 1,
        ...             "duration": 1,
        ...             "delay": 2,
        ...         }
        ...     ]
        ... }
        >>> len(active("transport_delay", "s", 1, world))
        1
    """
    return [
        disruption
        for disruption in world["disruptions"]
        if disruption["kind"] == kind
        and target in disruption["target"]
        and is_active(disruption, period)
    ]


def remaining_share(kind: str, target: str, period: int, world: JsonObject) -> Decimal:
    """Give the product of `1 - strength` of the active disruptions of a kind.

    Args:
        kind (str): The kind of disruption, one with a strength.
        target (str): The identifier of the target.
        period (int): The period.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: The share left, 1 when none acts.

    Examples:
        >>> remaining_share("quality_drop", "s", 1, {"disruptions": []})
        Decimal('1')
    """
    share = Decimal(1)
    for disruption in active(kind, target, period, world):
        share *= 1 - Decimal(disruption["strength"])
    return share


def price_factor(material_id: str, period: int, world: JsonObject) -> Decimal:
    """Give the product of the factors of the active price changes of a material.

    Args:
        material_id (str): The identifier of the material.
        period (int): The period.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: The product, 1 when none acts.

    Examples:
        >>> world = {
        ...     "disruptions": [
        ...         {
        ...             "kind": "price_change",
        ...             "target": ["chip"],
        ...             "start": 1,
        ...             "duration": 1,
        ...             "factor": Decimal("1.5"),
        ...         }
        ...     ]
        ... }
        >>> price_factor("chip", 1, world)
        Decimal('1.5')
    """
    factor = Decimal(1)
    for disruption in active("price_change", material_id, period, world):
        factor *= Decimal(disruption["factor"])
    return factor


def kept_condition(line_id: str, period: int, world: JsonObject) -> Decimal:
    """Give the share of condition a line keeps after the breakdowns of a period.

    Args:
        line_id (str): The identifier of the line.
        period (int): The period.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: The product of `1 - loss` of every `line_breakdown` and drawn
            breakdown of the period.

    Examples:
        >>> breakdowns = {"line-1": [{"breaks": True, "loss": Decimal("0.5")}]}
        >>> kept_condition("line-1", 1, {"disruptions": [], "breakdowns": breakdowns})
        Decimal('0.5')
    """
    kept = Decimal(1)
    for disruption in active("line_breakdown", line_id, period, world):
        kept *= 1 - Decimal(disruption["loss"])
    drawn = world["breakdowns"][line_id][period - 1]
    if drawn["breaks"]:
        kept *= 1 - Decimal(drawn["loss"])
    return kept


def good_share(line_id: str, item_id: str, period: int, world: JsonObject) -> Decimal:
    """Give the share of units started in a period that comes out good.

    Args:
        line_id (str): The identifier of the line.
        item_id (str): The identifier of the item.
        period (int): The period production starts.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: The yield times `1 - strength` of every active `yield_drop`.

    Examples:
        >>> world = {"disruptions": [], "yields": {"line-1/board": [Decimal("0.9")]}}
        >>> good_share("line-1", "board", 1, world)
        Decimal('0.9')
    """
    drawn = Decimal(world["yields"][f"{line_id}/{item_id}"][period - 1])
    return drawn * remaining_share("yield_drop", line_id, period, world)


def round_half_even(value: Decimal, exponent: Decimal) -> Decimal:
    """Round a value half to even, as the engine rounds what enters stock.

    Args:
        value (Decimal): The value.
        exponent (Decimal): The exponent to keep, such as `QUANTITY_EXPONENT`.

    Returns:
        Decimal: The rounded value.

    Examples:
        >>> round_half_even(Decimal("0.0025"), Decimal("0.001"))
        Decimal('0.002')
    """
    return value.quantize(exponent, rounding=ROUND_HALF_EVEN)


def entry_path(supplier_id: str, material_id: str) -> str:
    """Give the path of a catalogue entry.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.

    Returns:
        str: `suppliers.<supplier>.catalogue.<material>`.

    Examples:
        >>> entry_path("chip-maker", "chip")
        'suppliers.chip-maker.catalogue.chip'
    """
    return f"suppliers.{supplier_id}.catalogue.{material_id}"


def catalogue_price(
    supplier_id: str, material_id: str, period: int, world: JsonObject
) -> Decimal:
    """Give the catalogue price of a material in a period, before disruptions.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        period (int): The period, from 1.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: The price of the period under `prices` when the world draws it
            once per period, the parameter `price` otherwise.

    Examples:
        >>> world = {"prices": {"mill/steel": [Decimal("2.3"), Decimal("2.56")]}}
        >>> catalogue_price("mill", "steel", 2, world)
        Decimal('2.56')
    """
    prices = world.get("prices", {}).get(f"{supplier_id}/{material_id}")
    if prices is None:
        return parameter(f"{entry_path(supplier_id, material_id)}.price", world)
    return Decimal(prices[period - 1])


def delivery_of(
    supplier_id: str, material_id: str, placed: int, express: bool, world: JsonObject
) -> JsonObject:
    """Give the drawn delivery values of a buy: express or normal.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        placed (int): The period it is placed, from 1.
        express (bool): Whether it is an express order.
        world (dict[str, Any]): The world.

    Returns:
        dict[str, Any]: The delivery values of the period it is placed, under
            `express_deliveries` for an express order, under `deliveries` otherwise.

    Examples:
        >>> world = {
        ...     "deliveries": {"s/m": [{"punctual": True}]},
        ...     "express_deliveries": {"s/m": [{"punctual": False}]},
        ... }
        >>> delivery_of("s", "m", 1, True, world)
        {'punctual': False}
    """
    deliveries = world["express_deliveries" if express else "deliveries"]
    return deliveries[f"{supplier_id}/{material_id}"][placed - 1]


def first_arrival(
    supplier_id: str, material_id: str, placed: int, express: bool, world: JsonObject
) -> int:
    """Give the period a buy placed in a period first arrives.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        placed (int): The period it is placed.
        express (bool): Whether it is an express order.
        world (dict[str, Any]): The world.

    Returns:
        int: `placed + lead_time` (or `express_lead_time`), plus `delay` when the
            delivery is not punctual, plus the delays of the active transport delays
            of the supplier in that period.

    Examples:
        >>> path = "suppliers.s.catalogue.m.lead_time"
        >>> world = {
        ...     "parameters": {path: {"value": 2}},
        ...     "disruptions": [],
        ...     "deliveries": {"s/m": [{"punctual": False, "delay": 1}]},
        ... }
        >>> first_arrival("s", "m", 1, False, world)
        4
    """
    lead_time = "express_lead_time" if express else "lead_time"
    path = f"{entry_path(supplier_id, material_id)}.{lead_time}"
    delivery = delivery_of(supplier_id, material_id, placed, express, world)
    late = 0 if delivery["punctual"] else delivery["delay"]
    arrival = placed + int(parameter(path, world)) + late
    delays = active("transport_delay", supplier_id, arrival, world)
    return arrival + sum(int(disruption["delay"]) for disruption in delays)


def delivered_share(supplier_id: str, period: int, world: JsonObject) -> Decimal:
    """Give the share of a delivery left by outages and quality drops in a period.

    Args:
        supplier_id (str): The identifier of the supplier.
        period (int): The period of the delivery.
        world (dict[str, Any]): The world.

    Returns:
        Decimal: `outage(period) * quality(period)`.

    Examples:
        >>> delivered_share("s", 1, {"disruptions": []})
        Decimal('1')
    """
    outage = remaining_share("supplier_outage", supplier_id, period, world)
    return outage * remaining_share("quality_drop", supplier_id, period, world)


def option_arrivals(
    supplier_id: str,
    material_id: str,
    placed: int,
    express: bool,
    horizon: int,
    world: JsonObject,
) -> tuple[Arrival, ...]:
    """Give the arrivals of a buy, as shares of the quantity ordered.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        placed (int): The period it is placed.
        express (bool): Whether it is an express order.
        horizon (int): The horizon of the run.
        world (dict[str, Any]): The world.

    Returns:
        tuple[Arrival, ...]: The first arrival and the backfill, those within the
            horizon.

    Examples:
        >>> path = "suppliers.s.catalogue.m"
        >>> parameters = {
        ...     f"{path}.lead_time": {"value": 1},
        ...     f"{path}.backfill_delay": {"value": 0},
        ... }
        >>> delivery = {
        ...     "punctual": True,
        ...     "delay": 1,
        ...     "completeness": Decimal("0.9"),
        ...     "acceptance": Decimal(1),
        ... }
        >>> world = {
        ...     "parameters": parameters,
        ...     "disruptions": [],
        ...     "deliveries": {"s/m": [delivery]},
        ... }
        >>> option_arrivals("s", "m", 1, False, 3, world)
        (Arrival(period=2, accepted=Decimal('0.9'), left_open=Decimal('0')),)
    """
    delivery = delivery_of(supplier_id, material_id, placed, express, world)
    completeness = Decimal(delivery["completeness"])
    acceptance = Decimal(delivery["acceptance"])
    path = f"{entry_path(supplier_id, material_id)}.backfill_delay"
    backfill_delay = int(parameter(path, world))
    missing = 1 - completeness if backfill_delay > 0 else Decimal(0)
    arrival = first_arrival(supplier_id, material_id, placed, express, world)
    backfill = arrival + backfill_delay
    arrivals: list[Arrival] = []
    if arrival <= horizon:
        share = completeness * acceptance * delivered_share(supplier_id, arrival, world)
        arrivals.append(Arrival(period=arrival, accepted=share, left_open=missing))
    if arrival <= horizon and missing > 0 and backfill <= horizon:
        share = missing * acceptance * delivered_share(supplier_id, backfill, world)
        arrivals.append(Arrival(period=backfill, accepted=share, left_open=Decimal(0)))
    return tuple(arrivals)


def round_in_batch(
    before: Decimal, units: Decimal, share: Decimal
) -> tuple[Decimal, Decimal]:
    """Round a share of the units of an order or a production once for its batch.

    Args:
        before (Decimal): Units of the batch before the order or production.
        units (Decimal): Units of the order or production.
        share (Decimal): The share to take.

    Returns:
        tuple[Decimal, Decimal]: The rounded share of the units before it, and the
            rise of the rounded share that it adds.

    Examples:
        >>> round_in_batch(Decimal("0.001"), Decimal("0.001"), Decimal("0.6"))
        (Decimal('0.001'), Decimal('0.000'))
    """
    rounded_before = round_half_even(before * share, QUANTITY_EXPONENT)
    rounded = round_half_even((before + units) * share, QUANTITY_EXPONENT)
    return rounded_before, rounded - rounded_before


def order_arrivals(
    order: JsonObject,
    before: Decimal,
    first_period: int,
    horizon: int,
    world: JsonObject,
) -> tuple[Arrival, ...]:
    """Give the arrivals of an open supplier order, in units rounded as on delivery.

    A starting order arrives in full at its `expected_arrival`. An order whose first
    arrival is past waits for its backfill.

    Args:
        order (dict[str, Any]): The supplier order of the observation.
        before (Decimal): Open units of the orders of its batch before it.
        first_period (int): The current period.
        horizon (int): The horizon of the run.
        world (dict[str, Any]): The world.

    Returns:
        tuple[Arrival, ...]: Its arrivals within the horizon.

    Examples:
        >>> order = {"placed": 0, "expected_arrival": 2, "open_quantity": Decimal(100)}
        >>> order_arrivals(order, Decimal(0), 1, 3, {})
        (Arrival(period=2, accepted=Decimal('100'), left_open=Decimal('0')),)
    """
    units = Decimal(order["open_quantity"])
    zero = Decimal(0)
    if order["placed"] == 0:
        arrival = order["expected_arrival"]
        if arrival > horizon:
            return ()
        return (Arrival(period=arrival, accepted=units, left_open=zero),)
    supplier_id, material_id = order["supplier"], order["material"]
    delivery = delivery_of(
        supplier_id, material_id, order["placed"], order["express"], world
    )
    completeness = Decimal(delivery["completeness"])
    acceptance = Decimal(delivery["acceptance"])
    path = f"{entry_path(supplier_id, material_id)}.backfill_delay"
    backfill_delay = int(parameter(path, world))
    arrival = first_arrival(
        supplier_id, material_id, order["placed"], order["express"], world
    )
    backfill = arrival + backfill_delay
    arrivals: list[Arrival] = []
    missing = units
    if arrival > first_period:
        if arrival > horizon:
            return ()
        outage = remaining_share("supplier_outage", supplier_id, arrival, world)
        quality = remaining_share("quality_drop", supplier_id, arrival, world)
        sent_before, sent = round_in_batch(before, units, completeness)
        arrived_before, arrived = round_in_batch(sent_before, sent, outage)
        _, accepted = round_in_batch(arrived_before, arrived, acceptance * quality)
        missing = zero
        if backfill_delay > 0:
            missing = units - sent
        arrivals.append(Arrival(period=arrival, accepted=accepted, left_open=missing))
        # The backfills of the batch before the order are its units not sent.
        before -= sent_before
    if missing > 0 and backfill <= horizon:
        outage = remaining_share("supplier_outage", supplier_id, backfill, world)
        quality = remaining_share("quality_drop", supplier_id, backfill, world)
        arrived_before, arrived = round_in_batch(before, missing, outage)
        _, accepted = round_in_batch(arrived_before, arrived, acceptance * quality)
        arrivals.append(Arrival(period=backfill, accepted=accepted, left_open=zero))
    return tuple(arrivals)


def supplier_orders_of(
    observation: JsonObject, world: JsonObject
) -> tuple[SupplierOrder, ...]:
    """Give the open supplier orders of the observation with their arrivals.

    The normal or the express orders of one supplier, material and warehouse placed
    in one period that arrive in one period form a batch, rounded once, in the order
    of the observation.

    Args:
        observation (dict[str, Any]): The observation of the period.
        world (dict[str, Any]): The world.

    Returns:
        tuple[SupplierOrder, ...]: The orders, each with its arrivals.

    Examples:
        >>> order = {
        ...     "placed": 0,
        ...     "expected_arrival": 2,
        ...     "supplier": "s",
        ...     "material": "m",
        ...     "warehouse": "main",
        ...     "express": False,
        ...     "open_quantity": Decimal(100),
        ...     "unit_price": Decimal(1),
        ... }
        >>> observation = {"period": 1, "horizon": 3, "supplier_orders": [order]}
        >>> [order.open_quantity for order in supplier_orders_of(observation, {})]
        [Decimal('100')]
    """
    first, horizon = observation["period"], observation["horizon"]
    batch_open: dict[tuple[str, str, str, int, bool, int], Decimal] = {}
    supplier_orders: list[SupplierOrder] = []
    for order in observation["supplier_orders"]:
        supplier_id, material_id, placed = (
            order["supplier"],
            order["material"],
            order["placed"],
        )
        if placed == 0:
            arrival = order["expected_arrival"]
        else:
            arrival = first_arrival(
                supplier_id, material_id, placed, order["express"], world
            )
        batch = (
            supplier_id,
            material_id,
            order["warehouse"],
            placed,
            order["express"],
            arrival,
        )
        before = batch_open.get(batch, Decimal(0))
        units = Decimal(order["open_quantity"])
        batch_open[batch] = before + units
        supplier_orders.append(
            SupplierOrder(
                warehouse=order["warehouse"],
                material=material_id,
                open_quantity=units,
                unit_price=Decimal(order["unit_price"]),
                arrivals=order_arrivals(order, before, first, horizon, world),
            )
        )
    return tuple(supplier_orders)


def line_warehouse(line_id: str, manifest: JsonObject) -> str:
    """Give the warehouse of a line, the only warehouse when the line names none.

    Args:
        line_id (str): The identifier of the line.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        str: The identifier of the warehouse.

    Examples:
        >>> line_warehouse(
        ...     "line-1", {"lines": {"line-1": {}}, "warehouses": {"main": {}}}
        ... )
        'main'
    """
    return manifest["lines"][line_id].get("warehouse") or min(manifest["warehouses"])


def production_of(
    observation: JsonObject, world: JsonObject, manifest: JsonObject
) -> tuple[Production, ...]:
    """Give the production on the way of the observation with its good units.

    The productions of one line and item started in one period form a batch, whose
    good units are rounded once, in the order of the observation.

    Args:
        observation (dict[str, Any]): The observation of the period.
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        tuple[Production, ...]: The productions, each with its good units.

    Examples:
        >>> world = {
        ...     "parameters": {"lines.line-1.items.board.lead_time": {"value": 2}},
        ...     "yields": {"line-1/board": [Decimal("0.6")]},
        ...     "disruptions": [],
        ... }
        >>> manifest = {"lines": {"line-1": {}}, "warehouses": {"main": {}}}
        >>> made = {
        ...     "line": "line-1",
        ...     "item": "board",
        ...     "started": Decimal(1),
        ...     "ready": 2,
        ... }
        >>> production_of({"production": [made]}, world, manifest)[0].good
        Decimal('0.600')
    """
    batch_started: dict[tuple[str, str, int], Decimal] = {}
    production: list[Production] = []
    for made in observation["production"]:
        line_id, item_id = made["line"], made["item"]
        lead_time = parameter(f"lines.{line_id}.items.{item_id}.lead_time", world)
        start = made["ready"] - int(lead_time) + 1
        batch = (line_id, item_id, start)
        before = batch_started.get(batch, Decimal(0))
        units = Decimal(made["started"])
        batch_started[batch] = before + units
        share = good_share(line_id, item_id, start, world)
        production.append(
            Production(
                warehouse=line_warehouse(line_id, manifest),
                item=item_id,
                started=units,
                ready=made["ready"],
                good=round_in_batch(before, units, share)[1],
            )
        )
    return tuple(production)


def items_of(world: JsonObject, manifest: JsonObject) -> dict[str, Item]:
    """Give every item with its values from the world and its recipes.

    Args:
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, Item]: The items by identifier.

    Examples:
        >>> parameters = {
        ...     f"materials.chip.{key}": {"value": 1}
        ...     for key in ("space", "storage_cost", "salvage_value")
        ... }
        >>> manifest = {"materials": {"chip": {}}, "components": {}, "products": {}}
        >>> items_of({"parameters": parameters}, manifest)["chip"].space
        Decimal('1')
    """
    items: dict[str, Item] = {}
    for kind in ITEM_KINDS:
        for item_id, item in manifest[kind].items():
            path = f"{kind}.{item_id}"
            recipes = {
                recipe: {
                    input_id: Decimal(quantity) for input_id, quantity in inputs.items()
                }
                for recipe, inputs in item.get("recipes", {}).items()
            }
            items[item_id] = Item(
                space=parameter(f"{path}.space", world),
                storage_cost=parameter(f"{path}.storage_cost", world),
                salvage_value=parameter(f"{path}.salvage_value", world),
                recipes=recipes,
            )
    return items


def lines_of(
    periods: range, world: JsonObject, manifest: JsonObject
) -> dict[str, Line]:
    """Give every line with its values and its coefficients per period.

    Args:
        periods (range): The periods of the window.
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, Line]: The lines by identifier.

    Examples:
        >>> lines_of(range(1, 2), {}, {"lines": {}})
        {}
    """
    lines: dict[str, Line] = {}
    for line_id, line in manifest["lines"].items():
        path = f"lines.{line_id}"
        items = {
            item_id: LineItem(
                time=parameter(f"{path}.items.{item_id}.time", world),
                cost=parameter(f"{path}.items.{item_id}.cost", world),
                lead_time=int(parameter(f"{path}.items.{item_id}.lead_time", world)),
                good_shares={
                    period: good_share(line_id, item_id, period, world)
                    for period in periods
                },
                changeover_time=parameter_or_zero(
                    f"{path}.items.{item_id}.changeover_time", world
                ),
                changeover_cost=parameter_or_zero(
                    f"{path}.items.{item_id}.changeover_cost", world
                ),
            )
            for item_id in line["items"]
        }
        lines[line_id] = Line(
            warehouse=line_warehouse(line_id, manifest),
            capacity=parameter(f"{path}.capacity", world),
            wear_per_period=parameter(f"{path}.wear_per_period", world),
            wear_per_hour=parameter(f"{path}.wear_per_hour", world),
            repair_cost=parameter(f"{path}.repair_cost", world),
            repair_time=parameter(f"{path}.repair_time", world),
            repair_limit=parameter(f"{path}.repair_limit", world),
            overtime_hours=parameter(f"{path}.overtime_hours", world),
            overtime_cost=parameter_or_zero(f"{path}.overtime_cost", world),
            items=items,
            hour_shares={
                period: remaining_share("capacity_cut", line_id, period, world)
                for period in periods
            },
            kept_conditions={
                period: kept_condition(line_id, period, world) for period in periods
            },
        )
    return lines


def warehouses_of(observation: JsonObject, world: JsonObject) -> dict[str, Warehouse]:
    """Give every warehouse with its values and the items it accepts.

    The stock of the observation lists every item each warehouse accepts.

    Args:
        observation (dict[str, Any]): The observation of the period.
        world (dict[str, Any]): The world.

    Returns:
        dict[str, Warehouse]: The warehouses by identifier.

    Examples:
        >>> parameters = {
        ...     f"warehouses.main.{key}": {"value": 1}
        ...     for key in ("capacity", "storage_factor", "transport_factor")
        ... }
        >>> observation = {"stock": {"main": {"chip": 0}}}
        >>> warehouses_of(observation, {"parameters": parameters})["main"].accepts
        ('chip',)
    """
    return {
        warehouse_id: Warehouse(
            capacity=parameter(f"warehouses.{warehouse_id}.capacity", world),
            storage_factor=parameter(
                f"warehouses.{warehouse_id}.storage_factor", world
            ),
            transport_factor=parameter(
                f"warehouses.{warehouse_id}.transport_factor", world
            ),
            accepts=tuple(sorted(items)),
        )
        for warehouse_id, items in observation["stock"].items()
    }


def routes_of(world: JsonObject, manifest: JsonObject) -> tuple[Route, ...]:
    """Give every route with its values.

    Args:
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        tuple[Route, ...]: The routes, by source and destination.

    Examples:
        >>> parameters = {
        ...     "routes.a.b.cost": {"value": 1},
        ...     "routes.a.b.lead_time": {"value": 0},
        ... }
        >>> manifest = {"routes": {"a": {"b": {}}}}
        >>> routes_of({"parameters": parameters}, manifest)[0].lead_time
        0
    """
    routes: dict[str, JsonObject] = manifest.get("routes") or {}
    return tuple(
        Route(
            source=source,
            destination=destination,
            cost=parameter(f"routes.{source}.{destination}.cost", world),
            lead_time=int(parameter(f"routes.{source}.{destination}.lead_time", world)),
        )
        for source, reached in sorted(routes.items())
        for destination in sorted(reached)
    )


def customers_of(world: JsonObject, manifest: JsonObject) -> dict[str, Customer]:
    """Give every customer with its payment terms and the terms of its products.

    Args:
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        dict[str, Customer]: The customers by identifier.

    Examples:
        >>> parameters = {"customers.c.payment_terms": {"value": 2}}
        >>> manifest = {"customers": {"c": {"products": {}}}}
        >>> customers_of({"parameters": parameters}, manifest)["c"].payment_terms
        2
    """
    customers: dict[str, Customer] = {}
    for customer_id, customer in manifest["customers"].items():
        path = f"customers.{customer_id}"
        products = {
            product_id: CustomerProduct(
                price=parameter(f"{path}.products.{product_id}.price", world),
                transport_cost=parameter(
                    f"{path}.products.{product_id}.transport_cost", world
                ),
                late_penalty=parameter(
                    f"{path}.products.{product_id}.late_penalty", world
                ),
                lost_sale_penalty=parameter(
                    f"{path}.products.{product_id}.lost_sale_penalty", world
                ),
            )
            for product_id in customer["products"]
        }
        customers[customer_id] = Customer(
            payment_terms=int(parameter(f"{path}.payment_terms", world)),
            products=products,
        )
    return customers


def cash_of(world: JsonObject) -> Cash:
    """Give the rules of cash.

    Args:
        world (dict[str, Any]): The world.

    Returns:
        Cash: The credit limit and the three rates.

    Examples:
        >>> parameters = {
        ...     f"cash.{key}": {"value": 0}
        ...     for key in (
        ...         "credit_limit",
        ...         "credit_interest",
        ...         "debit_interest",
        ...         "overdraft_interest",
        ...     )
        ... }
        >>> cash_of({"parameters": parameters}).credit_limit
        Decimal('0')
    """
    return Cash(
        credit_limit=parameter("cash.credit_limit", world),
        credit_interest=parameter("cash.credit_interest", world),
        debit_interest=parameter("cash.debit_interest", world),
        overdraft_interest=parameter("cash.overdraft_interest", world),
    )


def state_of(
    observation: JsonObject, world: JsonObject, manifest: JsonObject
) -> WindowStart:
    """Give the state of the observation, with the arrivals and good units it awaits.

    Args:
        observation (dict[str, Any]): The observation of the period.
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        WindowStart: The state the observation shows.

    Examples:
        >>> observation = {
        ...     "period": 1,
        ...     "horizon": 1,
        ...     "cash": 5,
        ...     "stock": {},
        ...     "lines": {},
        ...     "production": [],
        ...     "transfers": [],
        ...     "supplier_orders": [],
        ...     "receivables": [],
        ... }
        >>> state_of(observation, {}, {}).cash
        Decimal('5')
    """
    return WindowStart(
        cash=Decimal(observation["cash"]),
        stock={
            warehouse_id: {item_id: Decimal(units) for item_id, units in items.items()}
            for warehouse_id, items in observation["stock"].items()
        },
        conditions={
            line_id: Decimal(line["condition"])
            for line_id, line in observation["lines"].items()
        },
        set_for={
            line_id: line.get("set_for")
            for line_id, line in observation["lines"].items()
        },
        hours={
            line_id: Hours(
                regular=Decimal(line["regular_hours_available"]),
                repair=Decimal(line["repair_hours_available"]),
                overtime=Decimal(line["overtime_hours_available"]),
            )
            for line_id, line in observation["lines"].items()
        },
        production=production_of(observation, world, manifest),
        transfers=tuple(
            TransferOnTheWay(
                item=transfer["item"],
                quantity=Decimal(transfer["quantity"]),
                destination=transfer["destination"],
                arrival=transfer["arrival"],
            )
            for transfer in observation["transfers"]
        ),
        supplier_orders=supplier_orders_of(observation, world),
        receivables=tuple(
            Receivable(
                amount=Decimal(receivable["amount"]),
                payment_period=receivable["payment_period"],
            )
            for receivable in observation["receivables"]
        ),
    )


def orders_of(
    customer_orders: list[JsonObject], observation: JsonObject
) -> tuple[CustomerOrder, ...]:
    """Give the customer orders open now and those that arrive later.

    Args:
        customer_orders (list[dict[str, Any]]): Every customer order of the run.
        observation (dict[str, Any]): The observation of the period.

    Returns:
        tuple[CustomerOrder, ...]: The orders, open ones with what is left of them.

    Examples:
        >>> later = {
        ...     "id": "order-2-1",
        ...     "customer": "c",
        ...     "product": "p",
        ...     "quantity": Decimal(4),
        ...     "shipped": 0,
        ...     "arrival": 2,
        ...     "due": 2,
        ...     "last": 2,
        ... }
        >>> orders = orders_of([later], {"period": 1, "customer_orders": []})
        >>> [order.id for order in orders]
        ['order-2-1']
    """
    later = [
        order for order in customer_orders if order["arrival"] > observation["period"]
    ]
    return tuple(
        CustomerOrder(
            id=order["id"],
            customer=order["customer"],
            product=order["product"],
            open_quantity=Decimal(order["quantity"]) - Decimal(order["shipped"]),
            arrival=order["arrival"],
            due=order["due"],
            last=order["last"],
        )
        for order in observation["customer_orders"] + later
    )


def buy_options_of(
    periods: range, horizon: int, world: JsonObject, manifest: JsonObject
) -> tuple[BuyOption, ...]:
    """Give every buy that can be placed in a period of the window.

    The unit price is the catalogue price of the period times the factors of the
    active price changes, rounded half to even to 4 places, plus `express_cost` with
    express; the buy limit is `max_quantity` times `1 - strength` of the active
    material shortages, rounded down to 3 places.

    Args:
        periods (range): The periods of the window.
        horizon (int): The last period whose arrivals are kept.
        world (dict[str, Any]): The world.
        manifest (dict[str, Any]): The manifest of the description.

    Returns:
        tuple[BuyOption, ...]: The options by supplier, material, period and
            express last.

    Examples:
        >>> buy_options_of(range(1, 2), 1, {}, {"suppliers": {}})
        ()
    """
    options: list[BuyOption] = []
    for supplier_id, supplier in sorted(manifest["suppliers"].items()):
        for material_id in sorted(supplier["catalogue"]):
            path = entry_path(supplier_id, material_id)
            express_choices = [False]
            if f"{path}.express_lead_time" in world["parameters"]:
                express_choices.append(True)
            for period in periods:
                price = round_half_even(
                    catalogue_price(supplier_id, material_id, period, world)
                    * price_factor(material_id, period, world),
                    PRICE_EXPONENT,
                )
                share = remaining_share("material_shortage", material_id, period, world)
                limit = (parameter(f"{path}.max_quantity", world) * share).quantize(
                    QUANTITY_EXPONENT, rounding=ROUND_FLOOR
                )
                for express in express_choices:
                    extra = Decimal(0)
                    if express:
                        extra = parameter(f"{path}.express_cost", world)
                    tiers = tuple(
                        Tier(
                            from_=from_,
                            unit_price=round_half_even(
                                tier_price * price_factor(material_id, period, world),
                                PRICE_EXPONENT,
                            )
                            + extra,
                        )
                        for from_, tier_price in discount_tiers(
                            supplier_id, material_id, supplier, world
                        )
                    )
                    options.append(
                        BuyOption(
                            supplier=supplier_id,
                            material=material_id,
                            period=period,
                            express=express,
                            unit_price=price + extra,
                            limit=limit,
                            arrivals=option_arrivals(
                                supplier_id,
                                material_id,
                                period,
                                express,
                                horizon,
                                world,
                            ),
                            min_quantity=parameter_or_zero(
                                f"{path}.min_quantity", world
                            ),
                            tiers=tiers,
                        )
                    )
    return tuple(options)


def discount_tiers(
    supplier_id: str, material_id: str, supplier: JsonObject, world: JsonObject
) -> list[tuple[Decimal, Decimal]]:
    """Give the `from` and the drawn price of every discount tier of an entry.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        supplier (dict[str, Any]): The supplier in the manifest of the description.
        world (dict[str, Any]): The world.

    Returns:
        list[tuple[Decimal, Decimal]]: The tiers by rising `from`.

    Examples:
        >>> world = {
        ...     "parameters": {
        ...         "suppliers.s.catalogue.chip.discounts.100.000.price": {"value": 4}
        ...     }
        ... }
        >>> supplier = {"catalogue": {"chip": {"discounts": [{"from": 100}]}}}
        >>> discount_tiers("s", "chip", supplier, world)
        [(Decimal('100.000'), Decimal('4'))]
    """
    tiers: list[tuple[Decimal, Decimal]] = []
    entry = supplier["catalogue"][material_id]
    for tier in entry.get("discounts", []):
        from_ = Decimal(tier["from"]).quantize(QUANTITY_EXPONENT)
        path = f"{entry_path(supplier_id, material_id)}.discounts.{from_}.price"
        tiers.append((from_, parameter(path, world)))
    return sorted(tiers)


def planning_input_of(
    observation: JsonObject,
    customer_orders: list[JsonObject],
    world: JsonObject,
    description: JsonObject,
) -> PlanningInput:
    """Give the planning input of the window from the period to the horizon.

    Args:
        observation (dict[str, Any]): The observation of the period.
        customer_orders (list[dict[str, Any]]): Every customer order of the run.
        world (dict[str, Any]): The world.
        description (dict[str, Any]): The description of the run.

    Returns:
        PlanningInput: Values from the world, structure from the description, and
            the state from the observation.

    Examples:
        >>> keys = (
        ...     "credit_limit",
        ...     "credit_interest",
        ...     "debit_interest",
        ...     "overdraft_interest",
        ... )
        >>> parameters = {f"cash.{key}": {"value": 0} for key in keys}
        >>> warehouse_keys = ("capacity", "storage_factor", "transport_factor")
        >>> parameters |= {
        ...     f"warehouses.main.{key}": {"value": 1} for key in warehouse_keys
        ... }
        >>> world = {"parameters": parameters, "disruptions": []}
        >>> kinds = (
        ...     "materials",
        ...     "components",
        ...     "products",
        ...     "lines",
        ...     "suppliers",
        ...     "customers",
        ...     "routes",
        ... )
        >>> manifest = dict.fromkeys(kinds, {}) | {"warehouses": {"main": {}}}
        >>> description = {"manifest": manifest, "scenario": {"start": {"cash": 1000}}}
        >>> lists = (
        ...     "production",
        ...     "transfers",
        ...     "supplier_orders",
        ...     "receivables",
        ...     "customer_orders",
        ... )
        >>> observation = {
        ...     "period": 1,
        ...     "horizon": 2,
        ...     "cash": 1000,
        ...     "stock": {"main": {}},
        ...     "lines": {},
        ... } | dict.fromkeys(lists, [])
        >>> planning_input_of(observation, [], world, description).first_period
        1
    """
    manifest = description["manifest"]
    periods = range(observation["period"], observation["horizon"] + 1)
    return PlanningInput(
        first_period=periods[0],
        window_end=periods[-1],
        horizon=periods[-1],
        starting_cash=Decimal(description["scenario"]["start"]["cash"]),
        items=items_of(world, manifest),
        lines=lines_of(periods, world, manifest),
        warehouses=warehouses_of(observation, world),
        routes=routes_of(world, manifest),
        customers=customers_of(world, manifest),
        cash=cash_of(world),
        state=state_of(observation, world, manifest),
        customer_orders=orders_of(customer_orders, observation),
        buy_options=buy_options_of(periods, periods[-1], world, manifest),
    )
