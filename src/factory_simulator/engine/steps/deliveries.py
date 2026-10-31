"""The arrivals of a period: deliveries, backfills and transfers.

Examples:
    >>> order = SupplierOrder(
    ...     id="buy-1-1",
    ...     supplier="mill",
    ...     material="steel",
    ...     warehouse="main",
    ...     quantity=Decimal(10),
    ...     open_quantity=Decimal(10),
    ...     unit_price=Decimal(2),
    ...     express=False,
    ...     placed=1,
    ...     arrival=2,
    ... )
    >>> stock = {"main": {"steel": Decimal(4)}}
    >>> add_to_stock(stock, order, Decimal(10))
    >>> stock
    {'main': {'steel': Decimal('14')}}
"""

from dataclasses import replace
from decimal import Decimal

from factory_simulator.engine.changes import Ledger, add_events, identifier_numbers
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.state import State, SupplierOrder, TransferOnTheWay
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to
from factory_simulator.engine.rules.disruptions import remaining_share
from factory_simulator.engine.rules.suppliers import delivery_outcome


def receive_deliveries(state: State, world: World) -> State:
    """Receive supplier orders, then backfills, then transfers that arrive.

    The normal or the express orders of one supplier, material and warehouse placed
    in one period that arrive in the period form a delivery batch, and so do their
    backfills; the shares of a batch are rounded once.

    Args:
        state (State): The state.
        world (World): The world.

    Returns:
        State: The state with the accepted units in stock and paid for, each order
            closed or left open for its backfill, and the arrived transfers in their
            destinations.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     Start,
        ...     StartSupplierOrder,
        ...     Supplier,
        ...     Warehouse,
        ...     build_state,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=one,
        ...     delay=0,
        ...     completeness=one,
        ...     acceptance=one,
        ... )
        >>> steel = Material(space=one, storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> started = StartSupplierOrder(
        ...     supplier="mill", material="steel", quantity=Decimal(10), arrival=1
        ... )
        >>> scenario = Scenario(horizon=1, start=Start(supplier_orders=(started,)))
        >>> world = draw_world(factory, scenario, seed=0)
        >>> state = replace(build_state(world), period=1)
        >>> receive_deliveries(state, world).stock["main"]["steel"]
        Decimal('10.000')
    """
    period = state.period
    ledger = Ledger(period, "receive_deliveries", state.cash, list(state.ledger))
    stock = {warehouse: dict(items) for warehouse, items in state.stock.items()}
    still_open: list[SupplierOrder] = []
    batch_open: dict[tuple[str, str, str, int, bool], Decimal] = {}
    for order in sorted(
        state.supplier_orders, key=lambda order: identifier_numbers(order.id)
    ):
        if order.backfill is None and order.arrival == period:
            batch = (
                order.supplier,
                order.material,
                order.warehouse,
                order.placed,
                order.express,
            )
            before = batch_open.get(batch, Decimal(0))
            batch_open[batch] = before + order.open_quantity
            accepted, left = receive_delivery(order, before, ledger, world)
            add_to_stock(stock, order, accepted)
            if left is not None:
                still_open.append(left)
        elif order.backfill != period:
            still_open.append(order)
    # Backfills come after every first delivery, in the events and in the ledger.
    batch_open = {}
    for order in sorted(
        state.supplier_orders, key=lambda order: identifier_numbers(order.id)
    ):
        if order.backfill == period:
            batch = (
                order.supplier,
                order.material,
                order.warehouse,
                order.placed,
                order.express,
            )
            before = batch_open.get(batch, Decimal(0))
            batch_open[batch] = before + order.open_quantity
            accepted = receive_backfill(order, before, ledger, world)
            add_to_stock(stock, order, accepted)
    on_the_way: list[TransferOnTheWay] = []
    for transfer in sorted(
        state.transfers, key=lambda transfer: identifier_numbers(transfer.id)
    ):
        if transfer.arrival != period:
            on_the_way.append(transfer)
            continue
        items = stock[transfer.destination]
        items[transfer.item] = items.get(transfer.item, Decimal(0)) + transfer.quantity
        ledger.add_event(
            "transfer_arrived",
            transfer.id,
            {
                "item": transfer.item,
                "quantity": transfer.quantity,
                "destination": transfer.destination,
            },
        )
    state = add_events(state, ledger.events)
    return replace(
        state,
        cash=ledger.cash,
        stock=read_only_copy(stock),
        supplier_orders=tuple(still_open),
        transfers=tuple(on_the_way),
        ledger=tuple(ledger.rows),
    )


def add_to_stock(
    stock: dict[str, dict[str, Decimal]], order: SupplierOrder, units: Decimal
) -> None:
    """Add units of the material of a supplier order to the stock of its warehouse.

    Args:
        stock (dict[str, dict[str, Decimal]]): Stock per warehouse and item, changed
            in place.
        order (SupplierOrder): The order.
        units (Decimal): The units that enter the stock.

    Examples:
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(10),
        ...     open_quantity=Decimal(10),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=2,
        ... )
        >>> stock = {"main": {"steel": Decimal(4)}}
        >>> add_to_stock(stock, order, Decimal(10))
        >>> stock
        {'main': {'steel': Decimal('14')}}
    """
    items = stock[order.warehouse]
    items[order.material] = items.get(order.material, Decimal(0)) + units


def round_in_batch(
    before: Decimal, units: Decimal, share: Decimal
) -> tuple[Decimal, Decimal]:
    """Round a share of the units of an order once for its whole batch.

    Args:
        before (Decimal): Units of the orders of the batch before the order.
        units (Decimal): Units of the order.
        share (Decimal): The share to take.

    Returns:
        tuple[Decimal, Decimal]: The rounded share of the units before the order, and
            the rise of the rounded share that the order adds.

    Examples:
        >>> round_in_batch(Decimal("0.001"), Decimal("0.001"), Decimal("0.6"))
        (Decimal('0.001'), Decimal('0.000'))
    """
    rounded_before = round_to(before * share, 3)
    return rounded_before, round_to((before + units) * share, 3) - rounded_before


def receive_delivery(
    order: SupplierOrder, before: Decimal, ledger: Ledger, world: World
) -> tuple[Decimal, SupplierOrder | None]:
    """Receive the first delivery of a supplier order.

    The part missing by completeness becomes the backfill when the catalogue entry
    has a `backfill_delay` above 0; the part held back by an outage is lost.

    Args:
        order (SupplierOrder): The order arriving in the period of the ledger.
        before (Decimal): Open units of the orders of its batch before it.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        tuple[Decimal, SupplierOrder | None]: The accepted units, and the order left
            open for its backfill or None when it closes.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     Supplier,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=one,
        ...     delay=0,
        ...     completeness=one,
        ...     acceptance=one,
        ... )
        >>> steel = Material(space=one, storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2), seed=0)
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(10),
        ...     open_quantity=Decimal(10),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=2,
        ... )
        >>> ledger = Ledger(
        ...     period=2, step="receive_deliveries", cash=Decimal(100), rows=[]
        ... )
        >>> receive_delivery(order, Decimal(0), ledger, world)
        (Decimal('10.000'), None)
        >>> ledger.cash
        Decimal('80.000')
    """
    period = ledger.period
    completeness, acceptance = Decimal(1), Decimal(1)
    outage, quality = Decimal(1), Decimal(1)
    if order.placed > 0:
        drawn = delivery_outcome(order, order.placed, world)
        completeness, acceptance = drawn.completeness, drawn.acceptance
        outage = remaining_share("supplier_outage", order.supplier, period, world)
        quality = remaining_share("quality_drop", order.supplier, period, world)
    # Each share is rounded once for the batch: completeness of the open units gives
    # the units sent, the outage of the units sent gives the units arrived, and
    # acceptance and quality of the units arrived give the units accepted.
    sent_before, sent = round_in_batch(before, order.open_quantity, completeness)
    arrived_before, arrived = round_in_batch(sent_before, sent, outage)
    _, accepted = round_in_batch(arrived_before, arrived, acceptance * quality)
    path = f"suppliers.{order.supplier}.catalogue.{order.material}.backfill_delay"
    backfill_delay = int(world.parameters[path])
    missing = Decimal(0)
    if backfill_delay > 0:
        missing = order.open_quantity - sent
    book_delivery(order, arrived, accepted, missing, ledger, backfill=False)
    if missing == 0:
        return accepted, None
    left = replace(order, open_quantity=missing, backfill=period + backfill_delay)
    return accepted, left


def receive_backfill(
    order: SupplierOrder, before: Decimal, ledger: Ledger, world: World
) -> Decimal:
    """Receive the backfill of a supplier order, which closes it.

    Args:
        order (SupplierOrder): The order whose backfill arrives in the period.
        before (Decimal): Open units of the backfills of its batch before it.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        Decimal: The accepted units.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     Supplier,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=one,
        ...     delay=0,
        ...     completeness=one,
        ...     acceptance=one,
        ... )
        >>> steel = Material(space=one, storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2), seed=0)
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(10),
        ...     open_quantity=Decimal(10),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=2,
        ... )
        >>> ledger = Ledger(
        ...     period=2, step="receive_deliveries", cash=Decimal(100), rows=[]
        ... )
        >>> receive_backfill(order, Decimal(0), ledger, world)
        Decimal('10.000')
    """
    period = ledger.period
    acceptance = delivery_outcome(order, order.placed, world).acceptance
    outage = remaining_share("supplier_outage", order.supplier, period, world)
    quality = remaining_share("quality_drop", order.supplier, period, world)
    arrived_before, arrived = round_in_batch(before, order.open_quantity, outage)
    _, accepted = round_in_batch(arrived_before, arrived, acceptance * quality)
    book_delivery(order, arrived, accepted, Decimal(0), ledger, backfill=True)
    return accepted


def book_delivery(
    order: SupplierOrder,
    arrived: Decimal,
    accepted: Decimal,
    missing: Decimal,
    ledger: Ledger,
    backfill: bool,
) -> None:
    """Book a delivery or a backfill: its event and its payment.

    Args:
        order (SupplierOrder): The order.
        arrived (Decimal): Units arrived.
        accepted (Decimal): Units that passed inspection.
        missing (Decimal): Units left for a backfill.
        ledger (Ledger): The ledger of the step, changed in place.
        backfill (bool): Whether this is a backfill.

    Examples:
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(10),
        ...     open_quantity=Decimal(10),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=2,
        ... )
        >>> ledger = Ledger(
        ...     period=2, step="receive_deliveries", cash=Decimal(100), rows=[]
        ... )
        >>> book_delivery(
        ...     order, Decimal(10), Decimal(9), Decimal(0), ledger, backfill=False
        ... )
        >>> ledger.cash
        Decimal('82')
    """
    payment = accepted * order.unit_price
    ledger.add_event(
        "delivery",
        order.id,
        {
            "ordered": order.open_quantity,
            "arrived": arrived,
            "accepted": accepted,
            "lost": order.open_quantity - missing - arrived,
            "payment": payment,
            "backfill": backfill,
        },
    )
    ledger.book("material_payment", -payment, order.id)
