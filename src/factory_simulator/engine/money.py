"""The money of a run: the interest on cash and the salvage value at the end.

Examples:
    >>> terms = Cash(
    ...     credit_limit=Decimal(0),
    ...     credit_interest=Decimal("0.01"),
    ...     debit_interest=Decimal(0),
    ...     overdraft_interest=Decimal(0),
    ... )
    >>> compute_interest(Decimal(200), terms)
    Decimal('2.0000')
"""

from decimal import ROUND_FLOOR, Decimal

from factory_simulator.engine.models.manifest import Cash
from factory_simulator.engine.models.state import State
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import in_decimal_context, round_to
from factory_simulator.engine.rules.items import salvage_of


@in_decimal_context
def compute_interest(cash: Decimal, cash_terms: Cash) -> Decimal:
    """Compute the interest on cash for one period, rounded against the factory.

    Interest earned is rounded down and interest paid up, to 4 places: the signed
    amount is always rounded towards minus infinity.

    Args:
        cash (Decimal): Cash before interest.
        cash_terms (Cash): The credit limit and the three rates.

    Returns:
        Decimal: Interest; positive when earned, negative when paid.

    Examples:
        >>> terms = Cash(
        ...     credit_limit=Decimal("1000"),
        ...     credit_interest=Decimal("0.0005"),
        ...     debit_interest=Decimal("0.0040"),
        ...     overdraft_interest=Decimal("0.0200"),
        ... )
        >>> compute_interest(Decimal("-1500"), terms)
        Decimal('-14.0000')
        >>> compute_interest(Decimal("1167.18"), terms)
        Decimal('0.5835')
    """
    limit = cash_terms.credit_limit
    if cash >= 0:
        interest = cash * cash_terms.credit_interest
    elif cash >= -limit:
        interest = cash * cash_terms.debit_interest
    else:
        interest = -(
            limit * cash_terms.debit_interest
            + (-cash - limit) * cash_terms.overdraft_interest
        )
    return round_to(interest, 4, ROUND_FLOOR)


@in_decimal_context
def compute_salvage(state: State, world: World) -> Decimal:
    """Compute the worth of the stock at the end of a run.

    Args:
        state (State): The state at the end.
        world (World): The world.

    Returns:
        Decimal: The sum of stock times salvage value over warehouses and items.

    Examples:
        >>> from factory_simulator.engine import Factory, Material, Scenario
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=Decimal(3))
        >>> factory = Factory(
        ...     materials={"steel": steel},
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
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=1),
        ...     parameters={"materials.steel.salvage_value": Decimal(3)},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={"main": {"steel": Decimal(10)}},
        ...     condition={},
        ...     customer_orders=(),
        ... )
        >>> compute_salvage(state, world)
        Decimal('30')
    """
    salvage = Decimal(0)
    for warehouse_id in sorted(state.stock):
        for item_id in sorted(state.stock[warehouse_id]):
            salvage += state.stock[warehouse_id][item_id] * salvage_of(item_id, world)
    return salvage


@in_decimal_context
def compute_profit(state: State, world: World) -> Decimal:
    """Compute the profit of a run at its end.

    Args:
        state (State): The state at the end.
        world (World): The world.

    Returns:
        Decimal: Cash at the end, less cash at the start of the scenario, plus
            receivables, plus salvage.

    Examples:
        >>> from factory_simulator.engine import Factory, Scenario
        >>> from factory_simulator.engine.models.scenario import Start
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
        >>> scenario = Scenario(horizon=1, start=Start(cash=Decimal(100)))
        >>> world = World(
        ...     factory=factory,
        ...     scenario=scenario,
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> state = State(
        ...     period=1, cash=Decimal(120), stock={}, condition={}, customer_orders=()
        ... )
        >>> compute_profit(state, world)
        Decimal('20')
    """
    receivables = sum(
        (receivable.amount for receivable in state.receivables), Decimal(0)
    )
    return (
        state.cash
        - world.scenario.start.cash
        + receivables
        + compute_salvage(state, world)
    )
