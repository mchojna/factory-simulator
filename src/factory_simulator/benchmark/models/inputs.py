"""The planning input of the profit program: the window, the factory and its state.

Examples:
    >>> from decimal import Decimal
    >>> Arrival(period=3, accepted=Decimal("0.95"), left_open=Decimal(0)).period
    3
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Item:
    """A material, component or product.

    Attributes:
        space (Decimal): Space one unit takes.
        storage_cost (Decimal): Cost of holding one unit for one period.
        salvage_value (Decimal): Worth of one unit in stock at the end.
        recipes (Mapping[str, Mapping[str, Decimal]]): The quantity of each input
            per unit, per recipe; empty for a material.

    Examples:
        >>> Item(
        ...     space=Decimal("0.01"),
        ...     storage_cost=Decimal(0),
        ...     salvage_value=Decimal("0.1"),
        ...     recipes={},
        ... ).recipes
        {}
    """

    space: Decimal
    storage_cost: Decimal
    salvage_value: Decimal
    recipes: Mapping[str, Mapping[str, Decimal]]


@dataclass(frozen=True, slots=True, kw_only=True)
class LineItem:
    """How a line makes one item.

    Attributes:
        time (Decimal): Hours per unit started.
        cost (Decimal): Cost per unit started.
        lead_time (int): Production started in t enters stock at the close of
            `t + lead_time - 1`.
        good_shares (Mapping[int, Decimal]): The share of units started in each
            period that comes out good.
        changeover_time (Decimal, optional): Hours to set the line for the item; 0
            without a changeover.
        changeover_cost (Decimal, optional): Cost to set the line for the item; 0
            without a changeover.

    Examples:
        >>> LineItem(
        ...     time=Decimal("0.5"),
        ...     cost=Decimal(2),
        ...     lead_time=1,
        ...     good_shares={1: Decimal(1)},
        ... ).changeover_time
        Decimal('0')
    """

    time: Decimal
    cost: Decimal
    lead_time: int
    good_shares: Mapping[int, Decimal]
    changeover_time: Decimal = Decimal(0)
    changeover_cost: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True, kw_only=True)
class Line:
    """A production line.

    Attributes:
        warehouse (str): Identifier of the warehouse of its inputs and output.
        capacity (Decimal): Production hours per period at condition 1.
        wear_per_period (Decimal): Share of condition lost every period.
        wear_per_hour (Decimal): Condition lost per production hour.
        repair_cost (Decimal): Cost of restoring a condition of 1.
        repair_time (Decimal): Hours used to restore a condition of 1.
        repair_limit (Decimal): Largest condition restored in one period.
        overtime_hours (Decimal): Extra hours per period at condition 1.
        overtime_cost (Decimal): Cost per overtime hour.
        items (Mapping[str, LineItem]): The items it makes.
        hour_shares (Mapping[int, Decimal]): The share of hours left in each period
            by every active `capacity_cut`.
        kept_conditions (Mapping[int, Decimal]): The share of condition kept by the
            breakdowns of each period.

    Examples:
        >>> line = Line(
        ...     warehouse="main",
        ...     capacity=Decimal(10),
        ...     wear_per_period=Decimal(0),
        ...     wear_per_hour=Decimal(0),
        ...     repair_cost=Decimal(0),
        ...     repair_time=Decimal(1),
        ...     repair_limit=Decimal(1),
        ...     overtime_hours=Decimal(0),
        ...     overtime_cost=Decimal(0),
        ...     items={},
        ...     hour_shares={},
        ...     kept_conditions={},
        ... )
        >>> line.warehouse
        'main'
    """

    warehouse: str
    capacity: Decimal
    wear_per_period: Decimal
    wear_per_hour: Decimal
    repair_cost: Decimal
    repair_time: Decimal
    repair_limit: Decimal
    overtime_hours: Decimal
    overtime_cost: Decimal
    items: Mapping[str, LineItem]
    hour_shares: Mapping[int, Decimal]
    kept_conditions: Mapping[int, Decimal]


@dataclass(frozen=True, slots=True, kw_only=True)
class Warehouse:
    """A warehouse.

    Attributes:
        capacity (Decimal): Space it has.
        storage_factor (Decimal): Factor on storage cost here.
        transport_factor (Decimal): Factor on the transport cost of shipments from
            here.
        accepts (tuple[str, ...]): Identifiers of the items it accepts, sorted.

    Examples:
        >>> Warehouse(
        ...     capacity=Decimal(100),
        ...     storage_factor=Decimal(1),
        ...     transport_factor=Decimal(1),
        ...     accepts=("chip",),
        ... ).accepts
        ('chip',)
    """

    capacity: Decimal
    storage_factor: Decimal
    transport_factor: Decimal
    accepts: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Route:
    """A one-way route between two warehouses.

    Attributes:
        source (str): Identifier of the warehouse it leaves.
        destination (str): Identifier of the warehouse it goes to.
        cost (Decimal): Cost per unit transferred.
        lead_time (int): Periods on the way; 0 arrives at once.

    Examples:
        >>> Route(
        ...     source="main", destination="centre", cost=Decimal("0.2"), lead_time=1
        ... ).lead_time
        1
    """

    source: str
    destination: str
    cost: Decimal
    lead_time: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomerProduct:
    """The terms on which a customer buys one product.

    Attributes:
        price (Decimal): Price of one shipped unit.
        transport_cost (Decimal): Cost of shipping one unit.
        late_penalty (Decimal): Penalty per unit not shipped, per period late.
        lost_sale_penalty (Decimal): Penalty per unit lost.

    Examples:
        >>> CustomerProduct(
        ...     price=Decimal(50),
        ...     transport_cost=Decimal(1),
        ...     late_penalty=Decimal(2),
        ...     lost_sale_penalty=Decimal(10),
        ... ).price
        Decimal('50')
    """

    price: Decimal
    transport_cost: Decimal
    late_penalty: Decimal
    lost_sale_penalty: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Customer:
    """A customer of products.

    Attributes:
        payment_terms (int): Periods from a shipment to its payment.
        products (Mapping[str, CustomerProduct]): The terms per product.

    Examples:
        >>> Customer(payment_terms=0, products={}).payment_terms
        0
    """

    payment_terms: int
    products: Mapping[str, CustomerProduct]


@dataclass(frozen=True, slots=True, kw_only=True)
class Cash:
    """The credit limit and interest rates of cash.

    Attributes:
        credit_limit (Decimal): Cash below minus this pays the overdraft rate.
        credit_interest (Decimal): Share of positive cash earned per period.
        debit_interest (Decimal): Share of negative cash down to the credit limit
            paid per period.
        overdraft_interest (Decimal): Share of negative cash below the credit limit
            paid per period.

    Examples:
        >>> Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal("0.01"),
        ...     debit_interest=Decimal("0.01"),
        ...     overdraft_interest=Decimal("0.01"),
        ... ).credit_interest
        Decimal('0.01')
    """

    credit_limit: Decimal
    credit_interest: Decimal
    debit_interest: Decimal
    overdraft_interest: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Arrival:
    """A delivery of a supplier order or of a buy option.

    Attributes:
        period (int): The period whose deliveries bring it.
        accepted (Decimal): Units accepted and paid, or for a buy option the share
            of the quantity ordered.
        left_open (Decimal): Units left open after it, or for a buy option the share
            of the quantity ordered.

    Examples:
        >>> Arrival(period=2, accepted=Decimal(1), left_open=Decimal(0)).accepted
        Decimal('1')
    """

    period: int
    accepted: Decimal
    left_open: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Tier:
    """A discount tier of a buy option: every unit of a buy of at least `from_`.

    Attributes:
        from_ (Decimal): The smallest quantity of the tier.
        unit_price (Decimal): The price paid per accepted unit, priced as the
            catalogue price of its option.

    Examples:
        >>> Tier(from_=Decimal(1000), unit_price=Decimal("4.6")).unit_price
        Decimal('4.6')
    """

    from_: Decimal
    unit_price: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class BuyOption:
    """A buy that can be placed in a period of the window.

    Attributes:
        supplier (str): Identifier of the supplier.
        material (str): Identifier of the material.
        period (int): The period it is placed.
        express (bool): Whether it is an express order.
        unit_price (Decimal): Price paid per accepted unit.
        limit (Decimal): The buy limit of the supplier and material in the period,
            express or not.
        arrivals (tuple[Arrival, ...]): Its arrivals within the horizon, in order.
        min_quantity (Decimal, optional): The smallest quantity of one order; 0
            without a minimum.
        tiers (tuple[Tier, ...], optional): The discount tiers, by rising `from_`.

    Examples:
        >>> option = BuyOption(
        ...     supplier="chip-maker",
        ...     material="chip",
        ...     period=1,
        ...     express=False,
        ...     unit_price=Decimal("0.5"),
        ...     limit=Decimal(1000),
        ...     arrivals=(),
        ... )
        >>> option.min_quantity
        Decimal('0')
    """

    supplier: str
    material: str
    period: int
    express: bool
    unit_price: Decimal
    limit: Decimal
    arrivals: tuple[Arrival, ...]
    min_quantity: Decimal = Decimal(0)
    tiers: tuple[Tier, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomerOrder:
    """A customer order open in the first period of the window or arriving later.

    Attributes:
        id (str): Identifier of the order.
        customer (str): Identifier of the customer.
        product (str): Identifier of the product.
        open_quantity (Decimal): Units not yet shipped.
        arrival (int): The period it arrives.
        due (int): The period it is due.
        last (int): The last period before the rest is lost.

    Examples:
        >>> CustomerOrder(
        ...     id="order-1-1",
        ...     customer="distributor",
        ...     product="monitor",
        ...     open_quantity=Decimal(4),
        ...     arrival=1,
        ...     due=1,
        ...     last=1,
        ... ).due
        1
    """

    id: str
    customer: str
    product: str
    open_quantity: Decimal
    arrival: int
    due: int
    last: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Hours:
    """The hours a line has available in the first period of the window.

    Attributes:
        regular (Decimal): Regular hours for production.
        repair (Decimal): Regular hours for production and repair.
        overtime (Decimal): Overtime hours.

    Examples:
        >>> Hours(regular=Decimal(10), repair=Decimal(10), overtime=Decimal(0)).regular
        Decimal('10')
    """

    regular: Decimal
    repair: Decimal
    overtime: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Production:
    """Units started on a line and not yet in stock.

    Attributes:
        warehouse (str): Identifier of the warehouse of its line.
        item (str): Identifier of the item.
        started (Decimal): Units started.
        ready (int): The period at whose close it enters stock.
        good (Decimal): Units that enter stock.

    Examples:
        >>> Production(
        ...     warehouse="main",
        ...     item="board",
        ...     started=Decimal(10),
        ...     ready=2,
        ...     good=Decimal(9),
        ... ).good
        Decimal('9')
    """

    warehouse: str
    item: str
    started: Decimal
    ready: int
    good: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class TransferOnTheWay:
    """Units in transfer along a route, not yet in their destination.

    Attributes:
        item (str): Identifier of the item.
        quantity (Decimal): Units transferred.
        destination (str): Identifier of the warehouse it goes to.
        arrival (int): The period whose deliveries bring it.

    Examples:
        >>> TransferOnTheWay(
        ...     item="monitor", quantity=Decimal(6), destination="centre", arrival=5
        ... ).arrival
        5
    """

    item: str
    quantity: Decimal
    destination: str
    arrival: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SupplierOrder:
    """An open supplier order.

    Attributes:
        warehouse (str): Identifier of the warehouse it goes to.
        material (str): Identifier of the material.
        open_quantity (Decimal): Units still to come.
        unit_price (Decimal): Price paid per accepted unit.
        arrivals (tuple[Arrival, ...]): Its arrivals within the horizon, in units.

    Examples:
        >>> SupplierOrder(
        ...     warehouse="main",
        ...     material="chip",
        ...     open_quantity=Decimal(100),
        ...     unit_price=Decimal("0.5"),
        ...     arrivals=(),
        ... ).open_quantity
        Decimal('100')
    """

    warehouse: str
    material: str
    open_quantity: Decimal
    unit_price: Decimal
    arrivals: tuple[Arrival, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Receivable:
    """Revenue of a shipment the customer pays later.

    Attributes:
        amount (Decimal): Money owed.
        payment_period (int): The period whose start pays it.

    Examples:
        >>> Receivable(amount=Decimal(500), payment_period=5).amount
        Decimal('500')
    """

    amount: Decimal
    payment_period: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowStart:
    """The state the observation of the first period of the window shows.

    Attributes:
        cash (Decimal): Money now.
        stock (Mapping[str, Mapping[str, Decimal]]): Units per warehouse and item.
        conditions (Mapping[str, Decimal]): The condition of every line.
        hours (Mapping[str, Hours]): The hours available of every line.
        production (tuple[Production, ...]): Production not yet in stock.
        transfers (tuple[TransferOnTheWay, ...]): Transfers on the way.
        supplier_orders (tuple[SupplierOrder, ...]): Open supplier orders.
        receivables (tuple[Receivable, ...]): Unpaid receivables.
        set_for (Mapping[str, str | None], optional): The item each line is set
            for, None for none.

    Examples:
        >>> start = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> start.set_for
        {}
    """

    cash: Decimal
    stock: Mapping[str, Mapping[str, Decimal]]
    conditions: Mapping[str, Decimal]
    hours: Mapping[str, Hours]
    production: tuple[Production, ...]
    transfers: tuple[TransferOnTheWay, ...]
    supplier_orders: tuple[SupplierOrder, ...]
    receivables: tuple[Receivable, ...]
    set_for: Mapping[str, str | None] = field(default_factory=dict[str, str | None])


@dataclass(frozen=True, slots=True, kw_only=True)
class TerminalValue:
    """The worth of the units of an item at the end of a window.

    Attributes:
        value (Decimal): Worth of one unit up to the expected use.
        expected_use (Decimal): Units the factory expects to use after the window.

    Examples:
        >>> TerminalValue(value=Decimal("6.06"), expected_use=Decimal(12)).value
        Decimal('6.06')
    """

    value: Decimal
    expected_use: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanningInput:
    """Everything the profit program of a window needs.

    Attributes:
        first_period (int): The first period of the window, the current period.
        window_end (int): The last period of the window.
        horizon (int): The last period of the run.
        starting_cash (Decimal): The cash at the start of the run.
        items (Mapping[str, Item]): Every material, component and product.
        lines (Mapping[str, Line]): Every line.
        warehouses (Mapping[str, Warehouse]): Every warehouse.
        routes (tuple[Route, ...]): Every route.
        customers (Mapping[str, Customer]): Every customer.
        cash (Cash): The rules of cash.
        state (WindowStart): The state at the start of the window.
        customer_orders (tuple[CustomerOrder, ...]): The customer orders open now or
            arriving later.
        buy_options (tuple[BuyOption, ...]): Every buy that can be placed in a
            period of the window.
        terminal_values (Mapping[str, TerminalValue], optional): The terminal value
            of every item that has one; empty without a terminal value.
        purchase_budget_cap (Decimal | None, optional): The most the buys of each
            period of the window may cost, whatever the cash; None for no limit.

    Examples:
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=3,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... ).terminal_values
        {}
    """

    first_period: int
    window_end: int
    horizon: int
    starting_cash: Decimal
    items: Mapping[str, Item]
    lines: Mapping[str, Line]
    warehouses: Mapping[str, Warehouse]
    routes: tuple[Route, ...]
    customers: Mapping[str, Customer]
    cash: Cash
    state: WindowStart
    customer_orders: tuple[CustomerOrder, ...]
    buy_options: tuple[BuyOption, ...]
    terminal_values: Mapping[str, TerminalValue] = field(
        default_factory=dict[str, TerminalValue]
    )
    purchase_budget_cap: Decimal | None = None

    def __post_init__(self) -> None:
        """Refuse a purchase budget cap that is not finite or is below 0.

        Raises:
            ValueError: If `purchase_budget_cap` is not finite or is below 0.
        """
        if self.purchase_budget_cap is not None and (
            not self.purchase_budget_cap.is_finite() or self.purchase_budget_cap < 0
        ):
            raise ValueError("purchase_budget_cap: is not finite or is below 0")
