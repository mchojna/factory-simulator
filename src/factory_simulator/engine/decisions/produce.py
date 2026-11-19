"""The decision produce: checks, reasons and execution.

Examples:
    >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
    >>> world = draw_world(
    ...     Factory(
    ...         materials={},
    ...         components={},
    ...         products={},
    ...         suppliers={},
    ...         customers={},
    ...         lines={},
    ...         warehouses={},
    ...         cash=Cash(
    ...             credit_limit=Decimal(0),
    ...             credit_interest=Decimal(0),
    ...             debit_interest=Decimal(0),
    ...             overdraft_interest=Decimal(0),
    ...         ),
    ...     ),
    ...     Scenario(horizon=4),
    ...     seed=0,
    ... )
    >>> plant = Plant(
    ...     period=1,
    ...     stock={"main": {}},
    ...     customer_orders={},
    ...     receivables=[],
    ...     condition={},
    ...     set_for={},
    ...     hours={},
    ...     changeover_hours={},
    ...     overtime_hours={},
    ...     repair_hours={},
    ...     repairs={},
    ...     production=[],
    ...     plans=[],
    ...     supplier_orders=[],
    ...     transfers=[],
    ... )
    >>> ledger = Ledger(period=1, step="execute_decisions", cash=Decimal(0), rows=[])
    >>> produce = Produce(
    ...     kind="produce",
    ...     line="press",
    ...     item="bolt",
    ...     quantity=Decimal(5),
    ...     recipe=None,
    ...     overtime=False,
    ...     start=None,
    ... )
    >>> execute_produce(produce, "1-1", plant, ledger, world).reason
    'unknown_line'
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import (
    Plant,
    remaining_hours,
    remaining_overtime_hours,
    space_held,
)
from factory_simulator.engine.models.decisions import Produce
from factory_simulator.engine.models.state import Outcome, Plan, Production
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.items import (
    inputs_of,
    line_warehouse,
    made_item,
    space_of,
)


def execute_produce(
    decision: Produce, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a produce decision that passes its checks: start its production.

    Args:
        decision (Produce): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Stock, hours and production, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        Outcome: The outcome of the decision.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> ledger = Ledger(period=1, step="execute_decisions", cash=zero, rows=[])
        >>> produce = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe=None,
        ...     overtime=False,
        ...     start=None,
        ... )
        >>> execute_produce(produce, "1-1", plant, ledger, world).reason
        'unknown_line'
    """
    period = plant.period
    start = period if decision.start is None else decision.start
    decision = replace(decision, start=start)
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    if not period <= start <= world.scenario.horizon:
        return rejected(reason="start_outside_horizon")
    line = world.factory.lines.get(decision.line)
    if line is None:
        return rejected(reason="unknown_line")
    if decision.item not in line.items:
        return rejected(reason="line_cannot_make_item")
    item = made_item(decision.item, world)
    decision = replace(decision, recipe=decision.recipe or item.default_recipe)
    rejected = partial(rejected, decision=decision)
    recipe = item.recipes.get(str(decision.recipe))
    if recipe is None:
        return rejected(reason="unknown_recipe")
    reference = "make-" + decision_id
    accepted = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=True
    )
    if start > period:
        plant.plans.append(
            Plan(
                id=reference,
                start=start,
                line=decision.line,
                item=decision.item,
                quantity=decision.quantity,
                recipe=str(decision.recipe),
                overtime=decision.overtime,
            )
        )
        return accepted(reference=reference)
    line_item_path = f"lines.{decision.line}.items.{decision.item}"
    hours = decision.quantity * world.parameters[f"{line_item_path}.time"]
    changeover = changeover_of(decision.line, decision.item, plant, world)
    changeover_hours = Decimal(0) if changeover is None else changeover[0]
    missing = missing_hours(decision, hours, changeover_hours, plant, world)
    if missing is not None:
        asked, available = missing
        return rejected(reason="not_enough_hours", asked=asked, available=available)
    warehouse = line_warehouse(decision.line, world.factory)
    stock = plant.stock[warehouse]
    inputs = inputs_of(decision.quantity, recipe)
    for input_id, needed in sorted(inputs.items()):
        in_stock = stock.get(input_id, Decimal(0))
        if needed > in_stock:
            return rejected(
                reason="not_enough_input",
                item=input_id,
                asked=needed,
                available=in_stock,
            )
    before = space_held(warehouse, plant, world)
    after = (
        before
        - sum(
            (inputs[input_id] * space_of(input_id, world) for input_id in inputs),
            Decimal(0),
        )
        + decision.quantity * space_of(decision.item, world)
    )
    capacity = world.factory.warehouses[warehouse].capacity
    if after > capacity:
        return rejected(
            reason="not_enough_space", asked=after - before, available=capacity - before
        )
    start_production(
        decision, reference, inputs, hours, changeover, plant, ledger, world
    )
    return accepted(reference=reference)


def missing_hours(
    decision: Produce,
    hours: Decimal,
    changeover_hours: Decimal,
    plant: Plant,
    world: World,
) -> tuple[Decimal, Decimal] | None:
    """Give the hours asked and the hours left of the limit a produce exceeds.

    The changeover always uses the hours left of `remaining_hours`; an overtime
    produce uses overtime hours for its production.

    Args:
        decision (Produce): The decision.
        hours (Decimal): The production hours of the decision.
        changeover_hours (Decimal): The changeover hours of the decision.
        plant (Plant): The condition and the hours used of every line.
        world (World): The world.

    Returns:
        tuple[Decimal, Decimal] | None: The hours asked and the hours left of the
            failing limit, or None when the decision fits.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={"lines.press.capacity": Decimal(25)},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={"press": Decimal(1)},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> produce = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(30),
        ...     recipe="r",
        ...     overtime=False,
        ...     start=1,
        ... )
        >>> missing_hours(produce, Decimal(30), zero, plant, world)
        (Decimal('30'), Decimal('25.000'))
    """
    hours_left = remaining_hours(decision.line, plant, world)
    if not decision.overtime:
        if hours + changeover_hours > hours_left:
            return hours + changeover_hours, hours_left
        return None
    if changeover_hours > hours_left:
        return changeover_hours, hours_left
    overtime_hours_left = remaining_overtime_hours(decision.line, plant, world)
    if hours > overtime_hours_left:
        return hours, overtime_hours_left
    return None


def start_production(
    decision: Produce,
    reference: str,
    inputs: Mapping[str, Decimal],
    hours: Decimal,
    changeover: tuple[Decimal, Decimal] | None,
    plant: Plant,
    ledger: Ledger,
    world: World,
) -> None:
    """Start a production: take its inputs, use its hours and pay its costs.

    Args:
        decision (Produce): The decision, its start and recipe filled in.
        reference (str): The identifier of the production, `make-<decision_id>`.
        inputs (Mapping[str, Decimal]): Units of each input it takes from stock.
        hours (Decimal): Its production hours.
        changeover (tuple[Decimal, Decimal] | None): Its changeover hours and cost,
            or None without a changeover.
        plant (Plant): Stock, hours and production, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Scenario,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=4), seed=0)
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {"steel": Decimal(10)}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> ledger = Ledger(
        ...     period=1, step="execute_decisions", cash=Decimal(100), rows=[]
        ... )
        >>> produce = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
        ...     start=1,
        ... )
        >>> start_production(
        ...     produce,
        ...     "make-1-1",
        ...     {"steel": Decimal(5)},
        ...     Decimal(5),
        ...     None,
        ...     plant,
        ...     ledger,
        ...     world,
        ... )
        >>> plant.stock["main"]["steel"], ledger.cash
        (Decimal('5'), Decimal('95'))
    """
    period = plant.period
    stock = plant.stock[line_warehouse(decision.line, world.factory)]
    for input_id in sorted(inputs):
        stock[input_id] = stock[input_id] - inputs[input_id]
    changeover_hours, changeover_cost = changeover or (Decimal(0), Decimal(0))
    used = plant.overtime_hours if decision.overtime else plant.hours
    used[decision.line] = used.get(decision.line, Decimal(0)) + hours
    plant.changeover_hours[decision.line] = (
        plant.changeover_hours.get(decision.line, Decimal(0)) + changeover_hours
    )
    plant.set_for[decision.line] = decision.item
    path = f"lines.{decision.line}"
    line_item_path = f"{path}.items.{decision.item}"
    plant.production.append(
        Production(
            id=reference,
            line=decision.line,
            item=decision.item,
            recipe=str(decision.recipe),
            started=decision.quantity,
            start=period,
            ready=period + int(world.parameters[f"{line_item_path}.lead_time"]) - 1,
            overtime=decision.overtime,
            changeover_hours=None if changeover is None else changeover_hours,
        )
    )
    cost = decision.quantity * world.parameters[f"{line_item_path}.cost"]
    ledger.book("production_cost", -cost, reference)
    if decision.overtime:
        overtime_cost = hours * world.parameters[f"{path}.overtime_cost"]
        ledger.book("overtime_cost", -overtime_cost, reference)
    ledger.book("changeover_cost", -changeover_cost, reference)


def changeover_of(
    line_id: str, item_id: str, plant: Plant, world: World
) -> tuple[Decimal, Decimal] | None:
    """Give the hours and cost of setting a line for an item, or None without one.

    A line item with a changeover time or cost pays a changeover when the line is set
    for another item or for none.

    Args:
        line_id (str): The identifier of the line.
        item_id (str): The identifier of the item.
        plant (Plant): The item each line is set for.
        world (World): The world.

    Returns:
        tuple[Decimal, Decimal] | None: The changeover hours and cost, each 0 when its
            key is left out; None when the production has no changeover.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Line, LineItem, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> bolt = LineItem(
        ...     time=zero, cost=zero, yield_=zero, changeover_time=Decimal(2)
        ... )
        >>> press = Line(
        ...     capacity=zero,
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=zero,
        ...     items={"bolt": bolt},
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> changeover = {"lines.press.items.bolt.changeover_time": Decimal(2)}
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters=changeover,
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={"press": None},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> changeover_of("press", "bolt", plant, world)
        (Decimal('2'), Decimal('0'))
    """
    terms = world.factory.lines[line_id].items[item_id]
    if terms.changeover_time is None and terms.changeover_cost is None:
        return None
    if plant.set_for[line_id] == item_id:
        return None
    path = f"lines.{line_id}.items.{item_id}"
    return (
        world.parameters.get(f"{path}.changeover_time", Decimal(0)),
        world.parameters.get(f"{path}.changeover_cost", Decimal(0)),
    )
