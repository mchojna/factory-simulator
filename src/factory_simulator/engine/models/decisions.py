"""The decisions: ship, produce, buy, repair, cancel, transfer and a submission.

Examples:
    >>> Repair(kind="repair", line="press", amount=Decimal("0.2")).amount
    Decimal('0.2')
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Ship:
    """A decision to ship a quantity of a customer order.

    Attributes:
        kind (str): "ship".
        order (str): The identifier of the customer order.
        quantity (Decimal): Units to ship; the interface accepts only quantities
            above 0.
        warehouse (str | None): The warehouse it leaves from; None for the only
            warehouse of the manifest.

    Examples:
        >>> ship = Ship(kind="ship", order="order-1-1", quantity=Decimal("4"))
        >>> ship.warehouse is None
        True
    """

    kind: str
    order: str
    quantity: Decimal
    warehouse: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Produce:
    """A decision to produce a quantity of an item on a line.

    Attributes:
        kind (str): "produce".
        line (str): The identifier of the line.
        item (str): The identifier of the component or product.
        quantity (Decimal): Units to start; the interface accepts only quantities
            above 0.
        recipe (str | None): The recipe; None for the default recipe of the item.
        overtime (bool): Whether to use overtime hours.
        start (int | None): The period to start in; None for the current period.

    Examples:
        >>> produce = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal("5"),
        ...     recipe=None,
        ...     overtime=False,
        ...     start=None,
        ... )
        >>> produce.quantity
        Decimal('5')
    """

    kind: str
    line: str
    item: str
    quantity: Decimal
    recipe: str | None
    overtime: bool
    start: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Buy:
    """A decision to buy a quantity of a material from a supplier.

    Attributes:
        kind (str): "buy".
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        quantity (Decimal): Units to order; the interface accepts only quantities
            above 0.
        express (bool): Whether to order at the express lead time.
        warehouse (str | None): The warehouse the delivery goes to; None for the
            only warehouse of the manifest.

    Examples:
        >>> buy = Buy(
        ...     kind="buy",
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal("30"),
        ...     express=False,
        ... )
        >>> buy.warehouse is None
        True
    """

    kind: str
    supplier: str
    material: str
    quantity: Decimal
    express: bool
    warehouse: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Repair:
    """A decision to restore an amount of the condition of a line.

    Attributes:
        kind (str): "repair".
        line (str): The identifier of the line.
        amount (Decimal): Condition to restore; the interface accepts only amounts
            above 0.

    Examples:
        >>> Repair(kind="repair", line="press", amount=Decimal("0.2")).line
        'press'
    """

    kind: str
    line: str
    amount: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Cancel:
    """A decision to cancel a plan, or a quantity of an open supplier order.

    Attributes:
        kind (str): "cancel".
        order (str): The identifier of the supplier order or plan.
        quantity (Decimal | None): Units to cancel; the interface accepts only
            quantities above 0. None when left out.

    Examples:
        >>> Cancel(kind="cancel", order="buy-1-1", quantity=None).order
        'buy-1-1'
    """

    kind: str
    order: str
    quantity: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Transfer:
    """A decision to transfer a quantity of an item along a route.

    Attributes:
        kind (str): "transfer".
        item (str): The identifier of the item.
        quantity (Decimal): Units to transfer; the interface accepts only quantities
            above 0.
        source (str): The warehouse it leaves.
        destination (str): The warehouse it reaches.

    Examples:
        >>> transfer = Transfer(
        ...     kind="transfer",
        ...     item="bolt",
        ...     quantity=Decimal("8"),
        ...     source="main",
        ...     destination="east",
        ... )
        >>> transfer.destination
        'east'
    """

    kind: str
    item: str
    quantity: Decimal
    source: str
    destination: str


type Decision = Ship | Produce | Buy | Repair | Cancel | Transfer


@dataclass(frozen=True, slots=True, kw_only=True)
class Decisions:
    """The decisions of one period.

    Attributes:
        period (int): The period the decisions are for.
        decisions (tuple[Ship | Produce | Buy | Repair | Cancel | Transfer, ...]): The
            decisions, in the order given.

    Examples:
        >>> cancel = Cancel(kind="cancel", order="buy-1-1", quantity=None)
        >>> len(Decisions(period=2, decisions=(cancel,)).decisions)
        1
    """

    period: int
    decisions: tuple[Decision, ...] = ()
