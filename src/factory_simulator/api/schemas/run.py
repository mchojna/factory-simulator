"""The models of runs: submissions of decisions and what a run answers.

Examples:
    >>> ForkCreate(period=3).period
    3
"""

from typing import Annotated, Literal

from pydantic import Field

from factory_simulator.api.core.numbers import (
    ExactNumber,
    Periods,
    Quantity,
    ReadOnlyList,
    ReadOnlyMapping,
    Seed,
    Share,
    StrictModel,
)


class ShipCreate(StrictModel):
    """A decision to ship a quantity of a customer order.

    Attributes:
        kind (Literal["ship"]): "ship".
        order (str): The identifier of the customer order.
        quantity (Decimal): Units to ship, above 0.
        warehouse (str | None, optional): The warehouse it leaves from; required
            when the manifest has several warehouses.

    Examples:
        >>> ShipCreate(kind="ship", order="order-1-1", quantity="4").quantity
        Decimal('4.000')
    """

    kind: Literal["ship"]
    order: str
    quantity: Annotated[Quantity, Field(gt=0)]
    warehouse: str | None = None


class ProduceCreate(StrictModel):
    """A decision to produce a quantity of an item on a line.

    Attributes:
        kind (Literal["produce"]): "produce".
        line (str): The identifier of the line.
        item (str): The identifier of the component or product.
        quantity (Decimal): Units to start, above 0.
        recipe (str | None, optional): The recipe; None for the item's default.
        overtime (bool, optional): Whether to use overtime hours.
        start (int | None, optional): The period to start in; None for the period
            of the submission.

    Examples:
        >>> body = {"kind": "produce", "line": "line-1", "item": "board"}
        >>> ProduceCreate(**body, quantity="20").overtime
        False
    """

    kind: Literal["produce"]
    line: str
    item: str
    quantity: Annotated[Quantity, Field(gt=0)]
    recipe: str | None = None
    overtime: bool = False
    start: Periods | None = None


class BuyCreate(StrictModel):
    """A decision to buy a quantity of a material from a supplier.

    Attributes:
        kind (Literal["buy"]): "buy".
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        quantity (Decimal): Units to order, above 0.
        express (bool, optional): Whether to order at the express lead time.
        warehouse (str | None, optional): The warehouse the delivery goes to;
            required when the manifest has several warehouses.

    Examples:
        >>> body = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
        >>> BuyCreate(**body, quantity="50").express
        False
    """

    kind: Literal["buy"]
    supplier: str
    material: str
    quantity: Annotated[Quantity, Field(gt=0)]
    express: bool = False
    warehouse: str | None = None


class RepairCreate(StrictModel):
    """A decision to restore an amount of the condition of a line.

    Attributes:
        kind (Literal["repair"]): "repair".
        line (str): The identifier of the line.
        amount (Decimal): Condition to restore, above 0.

    Examples:
        >>> RepairCreate(kind="repair", line="line-1", amount="0.2").amount
        Decimal('0.2000')
    """

    kind: Literal["repair"]
    line: str
    amount: Annotated[Share, Field(gt=0)]


class CancelCreate(StrictModel):
    """A decision to cancel a plan, or a quantity of an open supplier order.

    Attributes:
        kind (Literal["cancel"]): "cancel".
        order (str): The identifier of the supplier order or plan.
        quantity (Decimal | None, optional): Units to cancel, above 0.

    Examples:
        >>> CancelCreate(kind="cancel", order="buy-2-1", quantity="60").quantity
        Decimal('60.000')
    """

    kind: Literal["cancel"]
    order: str
    quantity: Annotated[Quantity, Field(gt=0)] | None = None


class TransferCreate(StrictModel):
    """A decision to transfer a quantity of an item along a route.

    Attributes:
        kind (Literal["transfer"]): "transfer".
        item (str): The identifier of the item.
        quantity (Decimal): Units to transfer, above 0.
        source (str): The warehouse it leaves.
        destination (str): The warehouse it reaches.

    Examples:
        >>> body = {"kind": "transfer", "item": "monitor", "quantity": "6"}
        >>> TransferCreate(**body, source="main", destination="centre").quantity
        Decimal('6.000')
    """

    kind: Literal["transfer"]
    item: str
    quantity: Annotated[Quantity, Field(gt=0)]
    source: str
    destination: str


type DecisionCreate = Annotated[
    ShipCreate
    | ProduceCreate
    | BuyCreate
    | RepairCreate
    | CancelCreate
    | TransferCreate,
    Field(discriminator="kind"),
]


class DecisionsCreate(StrictModel):
    """The decisions of one period.

    Attributes:
        period (int): The period the decisions are for.
        decisions (tuple[DecisionCreate, ...]): The decisions, in the order given.

    Examples:
        >>> DecisionsCreate(period=1, decisions=[]).decisions
        ()
    """

    period: Periods
    decisions: ReadOnlyList[DecisionCreate]


class RunCreate(StrictModel):
    """A request to start a run.

    Attributes:
        scenario_id (str): The identifier of the scenario.
        seed (int): The seed, a whole number from 0 to `2 ** 128 - 1`.

    Examples:
        >>> RunCreate(scenario_id="s-1", seed=7).seed
        7
    """

    scenario_id: str
    seed: Seed


class ForkCreate(StrictModel):
    """A request to start a new run from a period of a finished run.

    Attributes:
        period (int): The period the new run starts in, from 1 to the horizon.

    Examples:
        >>> ForkCreate(period=3).period
        3
    """

    period: Periods


class RunPublic(StrictModel):
    """A run.

    Attributes:
        id (str): The identifier, 32 hexadecimal digits.
        scenario_id (str): The identifier of its scenario.
        description (Mapping[str, object]): What the agent is told.
        period (int): The current period.
        finished (bool): Whether the last period is closed.

    Examples:
        >>> body = {"id": "a1", "scenario_id": "b2", "description": {}}
        >>> RunPublic(**body, period=1, finished=False).period
        1
    """

    id: str
    scenario_id: str
    description: ReadOnlyMapping[str, object]
    period: int
    finished: bool


class CustomerOrderPublic(StrictModel):
    """An open customer order.

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
        >>> body = {"id": "order-1-1", "customer": "retail", "product": "monitor"}
        >>> numbers = {"quantity": "10", "shipped": "0", "arrival": 1, "due": 3}
        >>> CustomerOrderPublic(**body, **numbers, last=5).quantity
        Decimal('10')
    """

    id: str
    customer: str
    product: str
    quantity: ExactNumber
    shipped: ExactNumber
    arrival: int
    due: int
    last: int


class OutcomePublic(StrictModel):
    """What happened to one decision.

    Attributes:
        decision_id (str): The identifier of the decision, `<period>-<n>`.
        decision (DecisionCreate): The decision as validated.
        accepted (bool): Whether the decision was executed.
        reference (str | None, optional): The identifier of what an accepted decision
            created.
        reason (str | None, optional): Why a rejected decision was rejected.
        asked (Decimal | None, optional): The number the decision asked for.
        available (Decimal | None, optional): The number that was available.
        item (str | None, optional): The input that was short, for `not_enough_input`;
            the item, for `not_accepted`.

    Examples:
        >>> repair = RepairCreate(kind="repair", line="line-1", amount="0.2")
        >>> OutcomePublic(decision_id="1-1", decision=repair, accepted=True).accepted
        True
    """

    decision_id: str
    decision: DecisionCreate
    accepted: bool
    reference: str | None = None
    reason: str | None = None
    asked: ExactNumber | None = None
    available: ExactNumber | None = None
    item: str | None = None


class ReceivablePublic(StrictModel):
    """Revenue of a shipment the customer pays later.

    Attributes:
        shipment (str): The identifier of the shipment, `ship-<period>-<n>`.
        customer (str): The identifier of the customer.
        amount (Decimal): The amount to be paid.
        payment_period (int): The period in whose `apply_events` it is paid.

    Examples:
        >>> body = {"shipment": "ship-1-1", "customer": "retail", "amount": "120"}
        >>> ReceivablePublic(**body, payment_period=3).amount
        Decimal('120')
    """

    shipment: str
    customer: str
    amount: ExactNumber
    payment_period: int


class WarehouseSpacePublic(StrictModel):
    """The space of a warehouse in the period.

    Attributes:
        used (Decimal): The space of the stock.
        reserved (Decimal): The space of production not yet in stock and of open
            supplier orders.
        capacity (Decimal): The space the warehouse has.

    Examples:
        >>> WarehouseSpacePublic(used="12", reserved="3", capacity="100").capacity
        Decimal('100')
    """

    used: ExactNumber
    reserved: ExactNumber
    capacity: ExactNumber


class LineHoursPublic(StrictModel):
    """The condition of a line, the item it is set for and its hours in the period.

    Attributes:
        condition (Decimal): The condition, from 0 to 1.
        set_for (str | None): The item the line is set for, or None.
        regular_hours_available (Decimal): Production hours, `capacity * cut *
            condition` rounded down to 3 places.
        repair_hours_available (Decimal): Production and repair hours together,
            `capacity * cut` rounded down to 3 places.
        overtime_hours_available (Decimal): Overtime hours, `overtime_hours * cut *
            condition` rounded down to 3 places.

    Examples:
        >>> from decimal import Decimal
        >>> hours = {"regular_hours_available": "36", "repair_hours_available": "40"}
        >>> line = {"condition": Decimal("0.9"), "set_for": None, **hours}
        >>> LineHoursPublic(**line, overtime_hours_available="0").condition
        Decimal('0.9')
    """

    condition: ExactNumber
    set_for: str | None
    regular_hours_available: ExactNumber
    repair_hours_available: ExactNumber
    overtime_hours_available: ExactNumber


class ProductionPublic(StrictModel):
    """Units started on a line and not yet in stock.

    Attributes:
        id (str): The identifier, `make-<period>-<n>`.
        line (str): The identifier of the line.
        item (str): The identifier of the item made.
        recipe (str): The recipe it was made with.
        started (Decimal): Units started.
        ready (int): The period at whose close the units enter stock.

    Examples:
        >>> body = {"id": "make-1-1", "line": "line-1", "item": "board"}
        >>> ProductionPublic(**body, recipe="main", started="20", ready=2).started
        Decimal('20')
    """

    id: str
    line: str
    item: str
    recipe: str
    started: ExactNumber
    ready: int


class PlanPublic(StrictModel):
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
        >>> body = {"id": "make-1-1", "start": 2, "line": "line-1", "item": "board"}
        >>> PlanPublic(**body, quantity="20", recipe="main", overtime=False).start
        2
    """

    id: str
    start: int
    line: str
    item: str
    quantity: ExactNumber
    recipe: str
    overtime: bool


class TransferPublic(StrictModel):
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
        >>> body = {"id": "transfer-1-1", "item": "monitor", "quantity": "6"}
        >>> places = {"source": "main", "destination": "centre", "arrival": 3}
        >>> TransferPublic(**body, **places).arrival
        3
    """

    id: str
    item: str
    quantity: ExactNumber
    source: str
    destination: str
    arrival: int


class SupplierOrderPublic(StrictModel):
    """An open supplier order.

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
        >>> body = {"id": "buy-1-1", "supplier": "chip-maker", "material": "chip"}
        >>> numbers = {"quantity": "50", "open_quantity": "50", "unit_price": "2"}
        >>> times = {"express": False, "placed": 1, "expected_arrival": 3}
        >>> SupplierOrderPublic(**body, **numbers, **times, warehouse="main").unit_price
        Decimal('2')
    """

    id: str
    supplier: str
    material: str
    warehouse: str
    quantity: ExactNumber
    open_quantity: ExactNumber
    unit_price: ExactNumber
    express: bool
    placed: int
    expected_arrival: int


class DisruptionPublic(StrictModel):
    """A disruption visible in the period: acting, or announced by its notice.

    Attributes:
        id (str): The identifier, `disruption-<n>`.
        kind (str): The kind, such as "capacity_cut".
        target (tuple[str, ...]): The sorted identifiers it acts on.
        start (int): The first period it acts.
        duration (int | None, optional): Periods it acts; absent for a line breakdown
            and when the scenario hides `disruptions.duration`.
        strength (Decimal | None, optional): The strength of an outage, shortage,
            quality drop or capacity cut.
        delay (int | None, optional): The delay of a transport delay.
        factor (Decimal | None, optional): The factor of a demand shock or price change.
        loss (Decimal | None, optional): The loss of a line breakdown.

    Examples:
        >>> body = {"id": "disruption-1", "kind": "capacity_cut", "target": ["line-1"]}
        >>> DisruptionPublic(**body, start=2, duration=3, strength="0.5").target
        ('line-1',)
    """

    id: str
    kind: str
    target: ReadOnlyList[str]
    start: int
    duration: int | None = None
    strength: ExactNumber | None = None
    delay: int | None = None
    factor: ExactNumber | None = None
    loss: ExactNumber | None = None


class ForecastPublic(StrictModel):
    """A forecast of the demand of a customer product for a coming period.

    Attributes:
        period (int): The period it forecasts.
        quantity (Decimal): The forecast demand.

    Examples:
        >>> ForecastPublic(period=4, quantity="25").quantity
        Decimal('25')
    """

    period: int
    quantity: ExactNumber


class ObservationPublic(StrictModel):
    """What the agent sees when deciding.

    Attributes:
        period (int): The current period.
        horizon (int): Number of periods.
        finished (bool): Whether the last period is closed.
        cash (Decimal): Cash now.
        receivables (tuple[ReceivablePublic, ...]): Unpaid receivables, by shipment
            identifier.
        stock (Mapping[str, Mapping[str, Decimal]]): Stock per warehouse and item.
        space (Mapping[str, WarehouseSpacePublic]): The space of each warehouse.
        lines (Mapping[str, LineHoursPublic]): The condition and hours of each line.
        production (tuple[ProductionPublic, ...]): Production not yet in stock.
        plans (tuple[PlanPublic, ...]): Plans not yet run.
        transfers (tuple[TransferPublic, ...]): Transfers on the way.
        customer_orders (tuple[CustomerOrderPublic, ...]): Open customer orders.
        supplier_orders (tuple[SupplierOrderPublic, ...]): Open supplier orders.
        disruptions (tuple[DisruptionPublic, ...]): Disruptions visible in the
            period.
        forecasts (Mapping[str, tuple[ForecastPublic, ...]]): Per targeted
            `<customer>/<product>`, the forecasts for the coming periods, by period.
        prices (Mapping[str, Mapping[str, Decimal]]): Per supplier and material
            whose price is drawn once per period, the price of the current period.
        outcomes (tuple[OutcomePublic, ...]): Outcomes of the decisions of the
            previous period.
        events (tuple[Mapping[str, object], ...]): Events since the previous
            observation, each `{"kind", "step", "reference", ...}`.

    Examples:
        >>> times = {"period": 1, "horizon": 12, "finished": False, "cash": "1000"}
        >>> mappings = {"stock": {}, "space": {}, "lines": {}, "forecasts": {}}
        >>> mappings |= {"prices": {}}
        >>> lists = ["receivables", "production", "plans", "transfers", "events"]
        >>> lists += ["customer_orders", "supplier_orders", "disruptions", "outcomes"]
        >>> empty = {name: [] for name in lists}
        >>> ObservationPublic(**times, **mappings, **empty).cash
        Decimal('1000')
    """

    period: int
    horizon: int
    finished: bool
    cash: ExactNumber
    receivables: ReadOnlyList[ReceivablePublic]
    stock: ReadOnlyMapping[str, ReadOnlyMapping[str, ExactNumber]]
    space: ReadOnlyMapping[str, WarehouseSpacePublic]
    lines: ReadOnlyMapping[str, LineHoursPublic]
    production: ReadOnlyList[ProductionPublic]
    plans: ReadOnlyList[PlanPublic]
    transfers: ReadOnlyList[TransferPublic]
    customer_orders: ReadOnlyList[CustomerOrderPublic]
    supplier_orders: ReadOnlyList[SupplierOrderPublic]
    disruptions: ReadOnlyList[DisruptionPublic]
    forecasts: ReadOnlyMapping[str, ReadOnlyList[ForecastPublic]]
    prices: ReadOnlyMapping[str, ReadOnlyMapping[str, ExactNumber]]
    outcomes: ReadOnlyList[OutcomePublic]
    events: ReadOnlyList[ReadOnlyMapping[str, object]]


class ChecksPublic(StrictModel):
    """The outcomes a list of decisions would have in the current period.

    Attributes:
        outcomes (tuple[OutcomePublic, ...]): The outcomes, in execution order, plans
            of the period first.

    Examples:
        >>> ChecksPublic(outcomes=[]).outcomes
        ()
    """

    outcomes: ReadOnlyList[OutcomePublic]


class PeriodsPublic(StrictModel):
    """Every closed period of a run.

    Attributes:
        periods (tuple[Mapping[str, object], ...]): One entry per closed period:
            `{"period", "steps", "ledger"}`.

    Examples:
        >>> PeriodsPublic(periods=[]).periods
        ()
    """

    periods: ReadOnlyList[ReadOnlyMapping[str, object]]


class ResultPublic(StrictModel):
    """The result of a finished run.

    Attributes:
        seed (int): The seed of the run.
        periods (int): Number of periods run.
        profit (Decimal): Profit.
        cash_at_start (Decimal): Cash before period 1.
        cash_at_end (Decimal): Cash after the last period.
        receivables (Decimal): Receivables open after the last period.
        terms (Mapping[str, Decimal]): Each term of profit; costs positive.
        measures (Mapping[str, object]): The measures of the whole run.

    Examples:
        >>> money = {"profit": "50", "cash_at_start": "1000", "cash_at_end": "1050"}
        >>> body = {"seed": 7, "periods": 12, "receivables": "0", **money}
        >>> ResultPublic(**body, terms={}, measures={}).profit
        Decimal('50')
    """

    seed: Seed
    periods: int
    profit: ExactNumber
    cash_at_start: ExactNumber
    cash_at_end: ExactNumber
    receivables: ExactNumber
    terms: ReadOnlyMapping[str, ExactNumber]
    measures: ReadOnlyMapping[str, object]
