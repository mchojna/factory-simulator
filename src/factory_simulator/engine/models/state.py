"""The state of a run: orders, ledger rows, events, outcomes and the observation.

Examples:
    >>> state = State(
    ...     period=0, cash=Decimal(0), stock={}, condition={}, customer_orders=()
    ... )
    >>> state.finished
    False
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.models.decisions import Decision
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.scenario import Disruption
from factory_simulator.engine.models.trace import Transition

# A value of an event: a text, a period, a number or a sorted list of identifiers.
type EventValue = str | int | Decimal | tuple[str, ...]
type Event = Mapping[str, EventValue]


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomerOrder:
    """An order of a customer for a quantity of one product.

    Attributes:
        id (str): The identifier, `order-<period>-<n>`.
        customer (str): The identifier of the customer.
        product (str): The identifier of the product.
        quantity (Decimal): Units ordered.
        shipped (Decimal): Units shipped so far.
        arrival (int): The period the order arrived.
        due (int): The due period.
        last (int): The last period before the rest is lost.

    Examples:
        >>> order = CustomerOrder(
        ...     id="order-1-1",
        ...     customer="shop",
        ...     product="bolt",
        ...     quantity=Decimal("10"),
        ...     shipped=Decimal("4"),
        ...     arrival=1,
        ...     due=2,
        ...     last=3,
        ... )
        >>> order.quantity - order.shipped
        Decimal('6')
    """

    id: str
    customer: str
    product: str
    quantity: Decimal
    shipped: Decimal
    arrival: int
    due: int
    last: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Production:
    """Units started on a line and not yet in stock.

    Attributes:
        id (str): The identifier, `make-<period>-<n>`.
        line (str): The identifier of the line.
        item (str): The identifier of the item made.
        recipe (str): The recipe it is made with.
        started (Decimal): Units started.
        start (int): The period it starts.
        ready (int): The period at whose close the units enter stock.
        overtime (bool): Whether it uses overtime hours.
        changeover_hours (Decimal | None): The hours of its changeover; None
            without a changeover.

    Examples:
        >>> production = Production(
        ...     id="make-1-1",
        ...     line="press",
        ...     item="bolt",
        ...     recipe="forged",
        ...     started=Decimal("5"),
        ...     start=1,
        ...     ready=2,
        ...     overtime=False,
        ... )
        >>> production.changeover_hours is None
        True
    """

    id: str
    line: str
    item: str
    recipe: str
    started: Decimal
    start: int
    ready: int
    overtime: bool
    changeover_hours: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """A produce decision that starts in a later period.

    Attributes:
        id (str): The identifier, `make-<period>-<n>` of the period it was decided.
        start (int): The period it runs in.
        line (str): The identifier of the line.
        item (str): The identifier of the item to make.
        quantity (Decimal): Units to start.
        recipe (str): The recipe.
        overtime (bool): Whether to use overtime hours.

    Examples:
        >>> plan = Plan(
        ...     id="make-1-1",
        ...     start=3,
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal("5"),
        ...     recipe="forged",
        ...     overtime=False,
        ... )
        >>> plan.start
        3
    """

    id: str
    start: int
    line: str
    item: str
    quantity: Decimal
    recipe: str
    overtime: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TransferOnTheWay:
    """Units in transfer along a route, not yet in their destination.

    Attributes:
        id (str): The identifier, `transfer-<period>-<n>`.
        item (str): The identifier of the item.
        quantity (Decimal): Units transferred.
        source (str): The warehouse it left.
        destination (str): The warehouse it reaches.
        arrival (int): The period in whose `receive_deliveries` it enters the
            destination.

    Examples:
        >>> transfer = TransferOnTheWay(
        ...     id="transfer-1-1",
        ...     item="bolt",
        ...     quantity=Decimal("8"),
        ...     source="main",
        ...     destination="east",
        ...     arrival=3,
        ... )
        >>> transfer.arrival
        3
    """

    id: str
    item: str
    quantity: Decimal
    source: str
    destination: str
    arrival: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SupplierOrder:
    """An order of a material from a supplier, open until it arrives.

    Attributes:
        id (str): The identifier, `buy-<period>-<n>`.
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        warehouse (str): The identifier of the warehouse its deliveries go to.
        quantity (Decimal): Units ordered.
        open_quantity (Decimal): Units still to arrive.
        unit_price (Decimal): The price per unit, fixed when the order was placed.
        express (bool): Whether it is an express order.
        placed (int): The period the order was placed, 0 for a starting order.
        arrival (int): The period of its first delivery; private for an order placed
            by a buy.
        backfill (int | None): The period its backfill arrives, private; None until
            a delivery leaves a backfill.
        tier (Decimal | None): The `from` of the discount tier it was priced at;
            None at the catalogue price.
        cancelled (Decimal): Units cancelled so far; not in the public state.

    Examples:
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal("30"),
        ...     open_quantity=Decimal("30"),
        ...     unit_price=Decimal("2.0000"),
        ...     express=False,
        ...     placed=1,
        ...     arrival=3,
        ... )
        >>> order.cancelled
        Decimal('0')
    """

    id: str
    supplier: str
    material: str
    warehouse: str
    quantity: Decimal
    open_quantity: Decimal
    unit_price: Decimal
    express: bool
    placed: int
    arrival: int
    backfill: int | None = None
    tier: Decimal | None = None
    cancelled: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True, kw_only=True)
class Receivable:
    """Revenue of a shipment the customer pays later.

    Attributes:
        shipment (str): The identifier of the shipment, `ship-<period>-<n>`.
        customer (str): The identifier of the customer.
        amount (Decimal): The amount to be paid.
        payment_period (int): The period in whose `apply_events` it is paid.

    Examples:
        >>> receivable = Receivable(
        ...     shipment="ship-1-1",
        ...     customer="shop",
        ...     amount=Decimal("20"),
        ...     payment_period=3,
        ... )
        >>> receivable.payment_period
        3
    """

    shipment: str
    customer: str
    amount: Decimal
    payment_period: int


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerRow:
    """One movement of cash.

    Attributes:
        period (int): The period of the movement.
        step (str): The name of the step.
        kind (str): The kind of movement, such as "storage_cost".
        amount (Decimal): The amount, positive when cash rises.
        cash_after (Decimal): Cash after the movement.
        reference (str): The identifier the movement belongs to; empty for interest.

    Examples:
        >>> row = LedgerRow(
        ...     period=1,
        ...     step="close_period",
        ...     kind="storage_cost",
        ...     amount=Decimal("-2.5000"),
        ...     cash_after=Decimal("97.5000"),
        ...     reference="main",
        ... )
        >>> row.cash_after
        Decimal('97.5000')
    """

    period: int
    step: str
    kind: str
    amount: Decimal
    cash_after: Decimal
    reference: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Outcome:
    """What happened to one decision.

    Attributes:
        decision_id (str): The identifier of the decision, `<period>-<n>`.
        decision (Ship | Produce | Buy | Repair | Cancel | Transfer): The decision as
            validated.
        accepted (bool): Whether the decision was executed.
        reference (str | None): The identifier of what an accepted decision created.
        reason (str | None): Why a rejected decision was rejected.
        asked (Decimal | None): The number the decision asked for.
        available (Decimal | None): The number that was available.
        item (str | None): The input that was short, for `not_enough_input`; the
            item, for `not_accepted`.

    Examples:
        >>> from factory_simulator.engine.models.decisions import Cancel
        >>> cancel = Cancel(kind="cancel", order="buy-1-1", quantity=None)
        >>> Outcome(decision_id="1-1", decision=cancel, accepted=True).reason is None
        True
    """

    decision_id: str
    decision: Decision
    accepted: bool
    reference: str | None = None
    reason: str | None = None
    asked: Decimal | None = None
    available: Decimal | None = None
    item: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WarehouseSpace:
    """The space of a warehouse in the period.

    Attributes:
        used (Decimal): The space of the stock.
        reserved (Decimal): The space of production not yet in stock, of open
            supplier orders and of transfers on the way to it.
        capacity (Decimal): The space the warehouse has.

    Examples:
        >>> space = WarehouseSpace(
        ...     used=Decimal("40"),
        ...     reserved=Decimal("10"),
        ...     capacity=Decimal("100"),
        ... )
        >>> space.capacity - space.used - space.reserved
        Decimal('50')
    """

    used: Decimal
    reserved: Decimal
    capacity: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class LineHours:
    """The condition of a line, the item it is set for and its hours in the period.

    Attributes:
        condition (Decimal): The condition.
        set_for (str | None): The item the line is set for, or None.
        regular_hours_available (Decimal): The hours available for production and
            changeover, `capacity * cut * condition` rounded down to 3 places.
        repair_hours_available (Decimal): The repair hours available for
            production, changeover and repair together, `capacity * cut` rounded
            down to 3 places.
        overtime_hours_available (Decimal): The overtime hours available,
            `overtime_hours * cut * condition` rounded down to 3 places.

    Examples:
        >>> hours = LineHours(
        ...     condition=Decimal("0.9000"),
        ...     set_for=None,
        ...     regular_hours_available=Decimal("36.000"),
        ...     repair_hours_available=Decimal("40.000"),
        ...     overtime_hours_available=Decimal("0.000"),
        ... )
        >>> hours.regular_hours_available
        Decimal('36.000')
    """

    condition: Decimal
    set_for: str | None
    regular_hours_available: Decimal
    repair_hours_available: Decimal
    overtime_hours_available: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionSeen:
    """Production not yet in stock as the agent sees it.

    Attributes:
        id (str): The identifier, `make-<period>-<n>`.
        line (str): The identifier of the line.
        item (str): The identifier of the item made.
        recipe (str): The recipe it is made with.
        started (Decimal): Units started.
        ready (int): The period at whose close the units enter stock.

    Examples:
        >>> seen = ProductionSeen(
        ...     id="make-1-1",
        ...     line="press",
        ...     item="bolt",
        ...     recipe="forged",
        ...     started=Decimal("5"),
        ...     ready=2,
        ... )
        >>> seen.started
        Decimal('5')
    """

    id: str
    line: str
    item: str
    recipe: str
    started: Decimal
    ready: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SupplierOrderSeen:
    """An open supplier order as the agent sees it.

    Attributes:
        id (str): The identifier, `buy-<period>-<n>`.
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        warehouse (str): The identifier of the warehouse its deliveries go to.
        quantity (Decimal): Units ordered.
        open_quantity (Decimal): Units still to arrive.
        unit_price (Decimal): The price per unit.
        express (bool): Whether it is an express order.
        placed (int): The period the order was placed, 0 for a starting order.
        expected_arrival (int): `placed` plus the lead time used, or the arrival of
            a starting order.

    Examples:
        >>> seen = SupplierOrderSeen(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal("30"),
        ...     open_quantity=Decimal("30"),
        ...     unit_price=Decimal("2.0000"),
        ...     express=False,
        ...     placed=1,
        ...     expected_arrival=4,
        ... )
        >>> seen.expected_arrival
        4
    """

    id: str
    supplier: str
    material: str
    warehouse: str
    quantity: Decimal
    open_quantity: Decimal
    unit_price: Decimal
    express: bool
    placed: int
    expected_arrival: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastSeen:
    """A forecast of the demand of a customer product for a coming period.

    Attributes:
        period (int): The period it forecasts.
        quantity (Decimal): The forecast demand.

    Examples:
        >>> ForecastSeen(period=3, quantity=Decimal("12.000")).quantity
        Decimal('12.000')
    """

    period: int
    quantity: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    """What the agent sees when deciding.

    Attributes:
        period (int): The current period.
        horizon (int): Number of periods.
        finished (bool): Whether the last period is closed.
        cash (Decimal): Cash now.
        receivables (tuple[Receivable, ...]): Unpaid receivables, by shipment
            identifier.
        stock (Mapping[str, Mapping[str, Decimal]]): Stock per warehouse and item.
        space (Mapping[str, WarehouseSpace]): The space of each warehouse.
        lines (Mapping[str, LineHours]): The condition and hours of each line.
        production (tuple[ProductionSeen, ...]): Production not yet in stock.
        plans (tuple[Plan, ...]): Plans not yet run, by identifier.
        transfers (tuple[TransferOnTheWay, ...]): Transfers on the way, by
            identifier.
        customer_orders (tuple[CustomerOrder, ...]): Open customer orders.
        supplier_orders (tuple[SupplierOrderSeen, ...]): Open supplier orders.
        disruptions (tuple[Disruption, ...]): Every disruption from its visible
            period, `start - notice`, to its last active period, each target the
            sorted identifiers it acts on.
        forecasts (Mapping[str, tuple[ForecastSeen, ...]]): Per targeted
            `<customer>/<product>`, the forecasts for the coming periods, by period.
        prices (Mapping[str, Mapping[str, Decimal]]): Per supplier and material
            whose price is drawn once per period, the price of the current period.
        outcomes (tuple[Outcome, ...]): Outcomes of the decisions of the previous
            period.
        events (tuple[Mapping[str, str | int | Decimal | tuple[str, ...]], ...]): Events
            since the previous observation.

    Examples:
        >>> observation = Observation(
        ...     period=1,
        ...     horizon=12,
        ...     finished=False,
        ...     cash=Decimal("100"),
        ...     receivables=(),
        ...     stock={},
        ...     space={},
        ...     lines={},
        ...     production=(),
        ...     plans=(),
        ...     transfers=(),
        ...     customer_orders=(),
        ...     supplier_orders=(),
        ...     disruptions=(),
        ...     forecasts={},
        ...     prices={},
        ...     outcomes=(),
        ...     events=(),
        ... )
        >>> observation.horizon
        12
    """

    period: int
    horizon: int
    finished: bool
    cash: Decimal
    receivables: tuple[Receivable, ...]
    stock: Mapping[str, Mapping[str, Decimal]]
    space: Mapping[str, WarehouseSpace]
    lines: Mapping[str, LineHours]
    production: tuple[ProductionSeen, ...]
    plans: tuple[Plan, ...]
    transfers: tuple[TransferOnTheWay, ...]
    customer_orders: tuple[CustomerOrder, ...]
    supplier_orders: tuple[SupplierOrderSeen, ...]
    disruptions: tuple[Disruption, ...]
    forecasts: Mapping[str, tuple[ForecastSeen, ...]]
    prices: Mapping[str, Mapping[str, Decimal]]
    outcomes: tuple[Outcome, ...]
    events: tuple[Event, ...]

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        for name in ("stock", "space", "lines", "forecasts", "prices"):
            object.__setattr__(self, name, read_only_copy(getattr(self, name)))


type Measures = Mapping[str, Mapping[str, Decimal | None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class Tallies:
    """The running totals behind the measures.

    Attributes:
        customer_orders (Mapping[str, CustomerOrder]): The customer orders open at
            the last close or not yet due, as created, by identifier.
        supplier_orders (Mapping[str, SupplierOrder]): The supplier orders open at
            the last close, as they stood then, by identifier.
        shipped_on_time (Mapping[str, Decimal]): Units of each customer order not yet
            due shipped so far.
        running (Mapping[str, Mapping[str, Decimal]]): The sum of each flow over the
            periods so far, by name and key, for the keys of the latest period only;
            a key the latest period does not hold is dropped with its sum.

    Examples:
        >>> tallies = Tallies(shipped_on_time={"order-1-1": Decimal("4")})
        >>> tallies.shipped_on_time["order-1-1"]
        Decimal('4')
    """

    customer_orders: Mapping[str, CustomerOrder] = field(
        default_factory=lambda: MappingProxyType({})
    )
    supplier_orders: Mapping[str, SupplierOrder] = field(
        default_factory=lambda: MappingProxyType({})
    )
    shipped_on_time: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    running: Mapping[str, Mapping[str, Decimal]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        for name in (
            "customer_orders",
            "supplier_orders",
            "shipped_on_time",
            "running",
        ):
            object.__setattr__(self, name, read_only_copy(getattr(self, name)))


@dataclass(frozen=True, slots=True, kw_only=True)
class State:
    """The state of a run after a step.

    Attributes:
        period (int): The current period, 0 before period 1.
        cash (Decimal): Cash now.
        stock (Mapping[str, Mapping[str, Decimal]]): Stock per warehouse and item.
        condition (Mapping[str, Decimal]): Condition per line.
        set_for (Mapping[str, str | None]): The item each line is set for, or None.
        customer_orders (tuple[CustomerOrder, ...]): Open customer orders, by
            identifier.
        receivables (tuple[Receivable, ...]): Unpaid receivables, by shipment
            identifier.
        production (tuple[Production, ...]): Units started and not yet in stock, by
            identifier.
        plans (tuple[Plan, ...]): Plans not yet run, by identifier.
        supplier_orders (tuple[SupplierOrder, ...]): Open supplier orders, by
            identifier.
        transfers (tuple[TransferOnTheWay, ...]): Transfers on the way, by
            identifier.
        repairs (Mapping[str, Decimal]): Condition restored per line by the repairs
            of the period, added at its close.
        finished (bool): Whether the last period is closed.
        ledger (tuple[LedgerRow, ...]): Movements of cash of the current period.
        events (tuple[Mapping[str, str | int | Decimal | tuple[str, ...]], ...]): Events
            since the previous observation.
        period_events (tuple[Mapping[str, str | int | Decimal | tuple[str, ...]], ...]):
            Events of the current period.
        outcomes (tuple[Outcome, ...]): Outcomes of the decisions of the last
            `execute_decisions`.
        observation (Observation | None): The observation built by
            `build_observation`.
        tallies (Tallies): The running totals behind the measures.
        trace (tuple[Transition, ...]): The transitions of the period so far; they
            take no part in the equality of states.
        measures (Mapping[str, Mapping[str, Decimal | None]]): The measures of the
            period by name and key, computed at its close.

    Examples:
        >>> state = State(
        ...     period=0,
        ...     cash=Decimal("100"),
        ...     stock={"main": {"steel": Decimal("10")}},
        ...     condition={"press": Decimal("1.0000")},
        ...     customer_orders=(),
        ... )
        >>> state.finished
        False
    """

    period: int
    cash: Decimal
    stock: Mapping[str, Mapping[str, Decimal]]
    condition: Mapping[str, Decimal]
    set_for: Mapping[str, str | None] = field(
        default_factory=lambda: MappingProxyType({})
    )
    customer_orders: tuple[CustomerOrder, ...]
    receivables: tuple[Receivable, ...] = ()
    production: tuple[Production, ...] = ()
    plans: tuple[Plan, ...] = ()
    supplier_orders: tuple[SupplierOrder, ...] = ()
    transfers: tuple[TransferOnTheWay, ...] = ()
    repairs: Mapping[str, Decimal] = field(default_factory=lambda: MappingProxyType({}))
    finished: bool = False
    ledger: tuple[LedgerRow, ...] = ()
    events: tuple[Event, ...] = ()
    period_events: tuple[Event, ...] = ()
    outcomes: tuple[Outcome, ...] = ()
    observation: Observation | None = None
    tallies: Tallies = field(default_factory=Tallies)
    trace: tuple[Transition, ...] = field(default=(), compare=False, repr=False)
    measures: Measures = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        for name in ("stock", "condition", "set_for", "repairs", "measures"):
            object.__setattr__(self, name, read_only_copy(getattr(self, name)))
