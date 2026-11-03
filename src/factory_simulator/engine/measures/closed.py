"""A closed period as the measures read it: state, orders, production, shared functions.

Examples:
    >>> values = zeros(["total", "customers.shop"])
    >>> add(values, ["total"], Decimal("2.5"))
    >>> values
    {'total': Decimal('2.5'), 'customers.shop': Decimal('0')}
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from factory_simulator.engine.models.state import (
    CustomerOrder,
    Event,
    Production,
    State,
    SupplierOrder,
)
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to


@dataclass(slots=True)
class ClosedPeriod:
    """What the measures of one period are computed from.

    Attributes:
        state (State): The state at the close.
        world (World): The world.
        customer_orders (dict[str, CustomerOrder]): The customer orders of the
            tallies and those created in the period, as created.
        supplier_orders (dict[str, SupplierOrder]): The supplier orders of the
            tallies and those open at the close.
        production (Mapping[str, Production]): Production not in stock after the
            decisions, by identifier.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> period.state.cash
        Decimal('-5')
    """

    state: State
    world: World
    customer_orders: dict[str, CustomerOrder]
    supplier_orders: dict[str, SupplierOrder]
    production: Mapping[str, Production]

    def events(self, kind: str) -> list[Event]:
        """Give the events of a kind in the period.

        Args:
            kind (str): The kind of event.

        Returns:
            list[Mapping[str, str | int | Decimal | tuple[str, ...]]]: The events, in
                order.

        Examples:
            >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
            >>> zero = Decimal(0)
            >>> factory = Factory(
            ...     materials={},
            ...     components={},
            ...     products={},
            ...     suppliers={},
            ...     customers={},
            ...     lines={},
            ...     warehouses={},
            ...     cash=Cash(
            ...         credit_limit=zero,
            ...         credit_interest=zero,
            ...         debit_interest=zero,
            ...         overdraft_interest=zero,
            ...     ),
            ... )
            >>> world = draw_world(factory, Scenario(horizon=1), 0)
            >>> state = State(
            ...     period=1,
            ...     cash=zero,
            ...     stock={},
            ...     condition={},
            ...     customer_orders=(),
            ...     period_events=({"kind": "breakdown"},),
            ... )
            >>> ClosedPeriod(
            ...     state=state,
            ...     world=world,
            ...     customer_orders={},
            ...     supplier_orders={},
            ...     production={},
            ... ).events("breakdown")
            [{'kind': 'breakdown'}]
        """
        return [event for event in self.state.period_events if event["kind"] == kind]

    def accepted[D](self, kind: type[D]) -> list[tuple[str | None, D]]:
        """Give the accepted decisions of a kind with their references.

        Args:
            kind (type[D]): The class of the decision.

        Returns:
            list[tuple[str | None, D]]: The reference and the decision of each.

        Examples:
            >>> from factory_simulator.engine import (
            ...     Cash,
            ...     Factory,
            ...     Outcome,
            ...     Repair,
            ...     Scenario,
            ...     draw_world,
            ... )
            >>> zero = Decimal(0)
            >>> factory = Factory(
            ...     materials={},
            ...     components={},
            ...     products={},
            ...     suppliers={},
            ...     customers={},
            ...     lines={},
            ...     warehouses={},
            ...     cash=Cash(
            ...         credit_limit=zero,
            ...         credit_interest=zero,
            ...         debit_interest=zero,
            ...         overdraft_interest=zero,
            ...     ),
            ... )
            >>> repair = Repair(kind="repair", line="press", amount=Decimal("0.5"))
            >>> outcome = Outcome(
            ...     decision_id="1-1",
            ...     decision=repair,
            ...     accepted=True,
            ...     reference="repair-1-1",
            ... )
            >>> state = State(
            ...     period=1,
            ...     cash=zero,
            ...     stock={},
            ...     condition={},
            ...     customer_orders=(),
            ...     outcomes=(outcome,),
            ... )
            >>> period = ClosedPeriod(
            ...     state=state,
            ...     world=draw_world(factory, Scenario(horizon=1), 0),
            ...     customer_orders={},
            ...     supplier_orders={},
            ...     production={},
            ... )
            >>> [reference for reference, _ in period.accepted(Repair)]
            ['repair-1-1']
        """
        return [
            (outcome.reference, outcome.decision)
            for outcome in self.state.outcomes
            if outcome.accepted and isinstance(outcome.decision, kind)
        ]


def customer_keys(world: World) -> list[str]:
    """Give every key of a customer measure.

    Args:
        world (World): The world.

    Returns:
        list[str]: `total`, then each customer, product and customer product.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Product,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> bolt = CustomerProduct(
        ...     price=zero,
        ...     transport_cost=zero,
        ...     demand=zero,
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={
        ...         "bolt": Product(
        ...             space=zero, storage_cost=zero, salvage_value=zero, recipes={}
        ...         )
        ...     },
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": bolt})},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> customer_keys(draw_world(factory, Scenario(horizon=1), 0))
        ['total', 'customers.shop', 'products.bolt', 'pairs.shop/bolt']
    """
    customers = world.factory.customers
    customer_products = sorted(
        (customer_id, product_id)
        for customer_id, customer in customers.items()
        for product_id in customer.products
    )
    return [
        "total",
        *(f"customers.{customer_id}" for customer_id in sorted(customers)),
        *(f"products.{product_id}" for product_id in sorted(world.factory.products)),
        *(
            f"pairs.{customer_id}/{product_id}"
            for customer_id, product_id in customer_products
        ),
    ]


def customer_product_keys(customer_id: str, product_id: str) -> list[str]:
    """Give the keys a customer measure of one customer product counts under.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.

    Returns:
        list[str]: `total`, the customer, the product and the customer product.

    Examples:
        >>> customer_product_keys("distributor", "monitor")[1:3]
        ['customers.distributor', 'products.monitor']
    """
    return [
        "total",
        f"customers.{customer_id}",
        f"products.{product_id}",
        f"pairs.{customer_id}/{product_id}",
    ]


def zeros(keys: Iterable[str]) -> dict[str, Decimal]:
    """Give a value of 0 for every key.

    Args:
        keys (Iterable[str]): The keys.

    Returns:
        dict[str, Decimal]: 0 per key.

    Examples:
        >>> zeros(["total", "lines.press"])
        {'total': Decimal('0'), 'lines.press': Decimal('0')}
    """
    return dict.fromkeys(keys, Decimal(0))


def add(values: dict[str, Decimal], keys: Iterable[str], amount: Decimal) -> None:
    """Add an amount to the value of every key.

    Args:
        values (dict[str, Decimal]): Values by key, changed in place.
        keys (Iterable[str]): The keys.
        amount (Decimal): The amount.

    Examples:
        >>> values = {"total": Decimal("1.5")}
        >>> add(values, ["total", "lines.press"], Decimal("2"))
        >>> values
        {'total': Decimal('3.5'), 'lines.press': Decimal('2')}
    """
    for key in keys:
        values[key] = values.get(key, Decimal(0)) + amount


def ratio(above: Decimal, below: Decimal) -> Decimal | None:
    """Give the ratio of two running totals, rounded half to even to 12 places.

    Args:
        above (Decimal): The numerator.
        below (Decimal): The denominator.

    Returns:
        Decimal | None: The ratio, or None when the denominator is 0.

    Examples:
        >>> ratio(Decimal(1), Decimal(3))
        Decimal('0.333333333333')
        >>> ratio(Decimal(1), Decimal(0)) is None
        True
    """
    if below == 0:
        return None
    return round_to(above / below, 12)


def costs_by_reference(kind: str, state: State) -> dict[str, Decimal]:
    """Give the amounts paid of one kind of ledger row by their references.

    Args:
        kind (str): The kind of ledger row.
        state (State): The state at the close.

    Returns:
        dict[str, Decimal]: The amount paid, positive, by reference.

    Examples:
        >>> from factory_simulator.engine.models.state import LedgerRow
        >>> row = LedgerRow(
        ...     period=1,
        ...     step="close_period",
        ...     kind="storage_cost",
        ...     amount=Decimal("-2.50"),
        ...     cash_after=Decimal("7.50"),
        ...     reference="main/steel",
        ... )
        >>> state = State(
        ...     period=1,
        ...     cash=Decimal("7.50"),
        ...     stock={},
        ...     condition={},
        ...     customer_orders=(),
        ...     ledger=(row,),
        ... )
        >>> costs_by_reference("storage_cost", state)
        {'main/steel': Decimal('2.50')}
    """
    return {row.reference: -row.amount for row in state.ledger if row.kind == kind}
