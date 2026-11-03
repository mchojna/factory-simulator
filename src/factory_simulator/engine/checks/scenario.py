"""The checks of a scenario: the rules that join it with its factory and its horizon.

Examples:
    >>> check_hidden(Scenario(horizon=4, hidden=("lines.breakdown_loss",) * 2))
    Traceback (most recent call last):
    ...
    factory_simulator.engine.numbers.InputError: hidden.1: repeats lines.breakdown_loss
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import cast

from factory_simulator.engine.checks.manifest import lowest_price
from factory_simulator.engine.models.manifest import Factory, Range
from factory_simulator.engine.models.scenario import DemandShape, Forecast, Scenario
from factory_simulator.engine.numbers import InputError, in_decimal_context
from factory_simulator.engine.rules.demand import shape_factor
from factory_simulator.engine.rules.items import is_accepted, items_of
from factory_simulator.engine.rules.parameters import (
    HIDDEN_GROUPS,
    MONEY_KEYS,
    largest,
    smallest,
    walk_parameters,
)
from factory_simulator.engine.rules.targets import (
    TARGET_KINDS,
    is_customer_product_targeted,
    targets_in,
)

# The smallest amount a run may not reach: 100 times below 10**26, the first amount
# with more than the 26 digits DECIMAL(38, 12) of the record holds before the point.
TOO_LARGE = Decimal(10) ** 24

# The kinds of cost of a run, each one amount per period.
COST_KIND_COUNT = 12

# A produce takes at least 0.001 of an input and a repair at least 0.001 hours, so a
# period holds at most 1000 changeovers per unit of stock and 1000 units of repair per
# hour of a line.
DECISIONS_PER_UNIT = 1000


@in_decimal_context
def check_scenario(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario that does not fit its factory or its horizon.

    Args:
        scenario (Scenario): The scenario read from a body.
        factory (Factory): The factory of its manifest.

    Raises:
        InputError: If a check fails, with the path and problem of the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> scenario = Scenario(horizon=4, hidden=("weather",))
        >>> check_scenario(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        hidden.0: is not a group that may be hidden
    """
    # The checks of kinds, hidden groups, rule names and drawn lengths need only the
    # scenario and run before the others.
    check_disruption_kinds(scenario)
    check_hidden(scenario)
    check_random_rules(scenario)
    check_random_lengths(scenario)
    check_scenario_references(scenario, factory)
    check_random_targets(scenario, factory)
    check_periods(scenario)
    check_starting_space(scenario, factory)
    check_forecasts(scenario, factory)
    check_price_changes(scenario, factory)
    check_materials_arrive(scenario, factory)
    check_amounts(scenario, factory)


def check_disruption_kinds(scenario: Scenario) -> None:
    """Refuse a scenario whose disruption or random disruption has an unknown kind.

    Args:
        scenario (Scenario): The scenario.

    Raises:
        InputError: If a kind is not a kind of disruption, at the `kind` of the first
            written disruption, then of the first random one.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Disruption
        >>> flood = Disruption(
        ...     id="disruption-1",
        ...     kind="flood",
        ...     target=None,
        ...     start=1,
        ...     duration=1,
        ...     effect=Decimal("0.5"),
        ... )
        >>> scenario = Scenario(horizon=4, disruptions=(flood,))
        >>> check_disruption_kinds(scenario)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        disruptions.0.kind: flood is not one of supplier_outage, material_shortage,
        quality_drop, transport_delay, demand_shock, line_breakdown, price_change,
        capacity_cut, yield_drop
    """
    kinds = ", ".join(TARGET_KINDS)
    for list_name, entries in (
        ("disruptions", scenario.disruptions),
        ("random_disruptions", scenario.random_disruptions),
    ):
        for position, entry in enumerate(entries):
            if entry.kind not in TARGET_KINDS:
                raise InputError(
                    f"{list_name}.{position}.kind: {entry.kind} is not one of {kinds}"
                )


def check_hidden(scenario: Scenario) -> None:
    """Refuse a scenario whose hidden list holds an unknown group or a group twice.

    Every hidden group is one of the nine, once.

    Args:
        scenario (Scenario): The scenario.

    Raises:
        InputError: If an entry is not a group or repeats one, at the first one.

    Examples:
        >>> scenario = Scenario(horizon=4, hidden=("lines.breakdown_loss",) * 2)
        >>> check_hidden(scenario)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        hidden.1: repeats lines.breakdown_loss
    """
    for position, group in enumerate(scenario.hidden):
        if group not in HIDDEN_GROUPS:
            raise InputError(f"hidden.{position}: is not a group that may be hidden")
        if group in scenario.hidden[:position]:
            raise InputError(f"hidden.{position}: repeats {group}")


def check_random_rules(scenario: Scenario) -> None:
    """Refuse a scenario whose random rules break a rule of names, starts or cascades.

    Random rules have unique names, start one way and cascade one level deep.

    A rule starts by `chance` or at a written `start`, never both, and `choose`
    goes only with `chance`. A cascade names another rule of the scenario that has
    no cascade of its own and no written start.

    Args:
        scenario (Scenario): The scenario.

    Raises:
        InputError: If a rule repeats an earlier one, at the name of the first one;
            if a rule with `start` has `chance` or `choose`, at that key; if a rule
            has neither `start` nor `chance`, at `chance`; if a cascade names no other
            rule or a rule with a written start, at its rule; if a raised rule has a
            cascade, at that cascade.

    Examples:
        >>> from factory_simulator.engine.models.scenario import RandomDisruption
        >>> strike = RandomDisruption(
        ...     name="strike",
        ...     kind="supplier_outage",
        ...     target=None,
        ...     chance=Decimal("0.1"),
        ...     duration=2,
        ...     effect=Decimal(1),
        ... )
        >>> scenario = Scenario(horizon=4, random_disruptions=(strike, strike))
        >>> check_random_rules(scenario)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        random_disruptions.1.name: repeats strike
    """
    names: set[str] = set()
    for position, rule in enumerate(scenario.random_disruptions):
        path = f"random_disruptions.{position}"
        if rule.name in names:
            raise InputError(f"{path}.name: repeats {rule.name}")
        names.add(rule.name)
        if rule.start is None and rule.chance is None:
            raise InputError(f"{path}.chance: Field required")
        if rule.start is not None and rule.chance is not None:
            raise InputError(f"{path}.chance: is not allowed with start")
        if rule.start is not None and rule.choose:
            raise InputError(f"{path}.choose: is not allowed with start")
    rules = {rule.name: rule for rule in scenario.random_disruptions}
    for position, rule in enumerate(scenario.random_disruptions):
        if rule.raises is None:
            continue
        path = f"random_disruptions.{position}.raises"
        raised = rules.get(rule.raises.rule)
        if raised is None:
            raise InputError(f"{path}.rule: names no random disruption")
        if raised is rule:
            raise InputError(f"{path}.rule: names its own rule")
        if raised.start is not None:
            raise InputError(f"{path}.rule: names a rule with a written start")
        if raised.raises is not None:
            raised_position = scenario.random_disruptions.index(raised)
            raise InputError(
                f"random_disruptions.{raised_position}.raises: "
                "is not allowed on a raised rule"
            )


def check_random_lengths(scenario: Scenario) -> None:
    """Refuse a scenario in which a drawn length may be below 1.

    Drawn durations and delays, cascade periods and `periods_ahead` are at least 1.

    Args:
        scenario (Scenario): The scenario.

    Raises:
        InputError: If the duration or delay of a rule may draw 0 or its cascade
            lasts below 1 period, at the first one; if a `periods_ahead` is below 1,
            at the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Range
        >>> from factory_simulator.engine.models.scenario import RandomDisruption
        >>> strike = RandomDisruption(
        ...     name="strike",
        ...     kind="supplier_outage",
        ...     target=None,
        ...     chance=Decimal("0.1"),
        ...     duration=Range(min=0, max=2),
        ...     effect=Decimal(1),
        ... )
        >>> scenario = Scenario(horizon=4, random_disruptions=(strike,))
        >>> check_random_lengths(scenario)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        random_disruptions.0.duration: is below 1
    """
    for position, rule in enumerate(scenario.random_disruptions):
        if rule.duration is not None and smallest(rule.duration) < 1:
            raise InputError(f"random_disruptions.{position}.duration: is below 1")
        if rule.kind == "transport_delay" and smallest(rule.effect) < 1:
            raise InputError(f"random_disruptions.{position}.delay: is below 1")
        if rule.raises is not None and rule.raises.periods < 1:
            raise InputError(
                f"random_disruptions.{position}.raises.periods: is below 1"
            )
    for position, entry in enumerate(scenario.forecasts):
        if entry.periods_ahead < 1:
            raise InputError(f"forecasts.{position}.periods_ahead: is below 1")


def check_scenario_references(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario in which an identifier names no object of the right kind.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If an identifier is wrong, at the key that holds the first one.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Start
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> start = Start(condition={"saw": Decimal("0.9000")})
        >>> scenario = Scenario(horizon=4, start=start)
        >>> check_scenario_references(scenario, factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: start.condition.saw: is not a line
    """
    items = items_of(factory)
    start = scenario.start
    for line_id in start.condition:
        if line_id not in factory.lines:
            raise InputError(f"start.condition.{line_id}: is not a line")
    for warehouse_id, stock in start.stock.items():
        if warehouse_id not in factory.warehouses:
            raise InputError(f"start.stock.{warehouse_id}: is not a warehouse")
        for item_id in stock:
            if item_id not in items:
                raise InputError(
                    f"start.stock.{warehouse_id}.{item_id}: is not an item"
                )
    for position, order in enumerate(start.customer_orders):
        path = f"start.customer_orders.{position}"
        customer = factory.customers.get(order.customer)
        if customer is None:
            raise InputError(f"{path}.customer: is not a customer")
        if order.product not in customer.products:
            raise InputError(f"{path}.product: is not bought by the customer")
    for position, order in enumerate(start.supplier_orders):
        path = f"start.supplier_orders.{position}"
        supplier = factory.suppliers.get(order.supplier)
        if supplier is None:
            raise InputError(f"{path}.supplier: is not a supplier")
        if order.material not in supplier.catalogue:
            raise InputError(
                f"{path}.material: is not in the catalogue of the supplier"
            )
        if order.warehouse is None and len(factory.warehouses) > 1:
            raise InputError(f"{path}.warehouse: Field required")
        if order.warehouse is not None and order.warehouse not in factory.warehouses:
            raise InputError(f"{path}.warehouse: is not a warehouse")
    for line_id, item_id in start.set_for.items():
        line = factory.lines.get(line_id)
        if line is None:
            raise InputError(f"start.set_for.{line_id}: is not a line")
        if item_id not in line.items:
            raise InputError(f"start.set_for.{line_id}: is not made by the line")
    for position, disruption in enumerate(scenario.disruptions):
        if disruption.group is not None:
            check_group_target(
                disruption.group,
                (TARGET_KINDS[disruption.kind],),
                f"disruptions.{position}.target",
                factory,
            )
        check_listed_target(
            disruption.target,
            getattr(factory, TARGET_KINDS[disruption.kind]),
            f"disruptions.{position}.target",
        )
    for position, shape in enumerate(scenario.demand_shapes):
        check_shape_target(shape, f"demand_shapes.{position}.target", factory)
    for position, entry in enumerate(scenario.forecasts):
        check_shape_target(entry, f"forecasts.{position}.target", factory)


def check_shape_target(
    entry: DemandShape | Forecast, path: str, factory: Factory
) -> None:
    """Refuse a demand shape or forecast entry whose target names nothing.

    Args:
        entry (Trend | Season | Step | Ramp | SCurve | Forecast): The shape or the
            entry.
        path (str): The path of its target.
        factory (Factory): The factory.

    Raises:
        InputError: If the target names nothing of the manifest, at its path.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Trend
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> trend = Trend(customer="shop", product=None, rate=Decimal("0.01"))
        >>> path = "demand_shapes.0.target"
        >>> check_shape_target(trend, path, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        demand_shapes.0.target: names no customer
    """
    if entry.group is not None:
        check_group_target(entry.group, ("customers", "products"), path, factory)
    customer = factory.customers.get(entry.customer or "")
    if entry.customer is not None and customer is None:
        raise InputError(f"{path}: names no customer")
    if entry.product is not None and (
        entry.product not in factory.products
        or (customer is not None and entry.product not in customer.products)
    ):
        raise InputError(f"{path}: names a pair the manifest lacks")


def check_group_target(
    group: tuple[str, str], member_types: tuple[str, ...], path: str, factory: Factory
) -> None:
    """Refuse a group target whose group is missing, of another kind or empty.

    A group of members of a type the target may not have is refused too.

    Args:
        group (tuple[str, str]): The kind and identifier the target names.
        member_types (tuple[str, ...]): The types of member the target may have.
        path (str): The path of the target.
        factory (Factory): The factory.

    Raises:
        InputError: If the group is missing, of another kind, without members or of
            another member type, at the path of the target.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> check_group_target(("region", "east"), ("suppliers",), "target", factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: target: names no group east
    """
    kind, group_id = group
    named = factory.groups.get(group_id)
    if named is None:
        raise InputError(f"{path}: names no group {group_id}")
    if named.kind != kind:
        raise InputError(f"{path}: {group_id} is of kind {named.kind}, not {kind}")
    if not named.members:
        raise InputError(f"{path}: {group_id} has no members")
    if named.member_type not in member_types:
        raise InputError(f"{path}: {group_id} holds {named.member_type}")


def check_random_targets(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario whose random disruption names a target of another kind.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If a rule names something else, at the target of the first one.

    Examples:
        >>> from factory_simulator.engine.models.scenario import RandomDisruption
        >>> strike = RandomDisruption(
        ...     name="strike",
        ...     kind="supplier_outage",
        ...     target=("mill",),
        ...     chance=Decimal("0.1"),
        ...     duration=2,
        ...     effect=Decimal(1),
        ... )
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> scenario = Scenario(horizon=4, random_disruptions=(strike,))
        >>> check_random_targets(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        random_disruptions.0.target: names mill, not one of its kind
    """
    for position, rule in enumerate(scenario.random_disruptions):
        path = f"random_disruptions.{position}.target"
        if rule.group is not None:
            check_group_target(rule.group, (TARGET_KINDS[rule.kind],), path, factory)
        check_listed_target(
            rule.target, getattr(factory, TARGET_KINDS[rule.kind]), path
        )


def check_listed_target(
    target: tuple[str, ...] | None, known: Mapping[str, object], path: str
) -> None:
    """Refuse a target given as a list of identifiers that breaks a rule.

    The list names at least one object of its kind, each once.

    Args:
        target (tuple[str, ...] | None): The identifiers; None for all or a group.
        known (Mapping[str, object]): The objects of the kind it names.
        path (str): The path of the target.

    Raises:
        InputError: If the target is empty or names another kind, at the target;
            if an identifier repeats, at its second entry.

    Examples:
        >>> check_listed_target(("mill", "mill"), {"mill": "a supplier"}, "target")
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: target.1: repeats mill
    """
    if target is None:
        return
    if not target:
        raise InputError(f"{path}: names nothing")
    for position, identifier in enumerate(target):
        if identifier not in known:
            raise InputError(f"{path}: names {identifier}, not one of its kind")
        if identifier in target[:position]:
            raise InputError(f"{path}.{position}: repeats {identifier}")


def check_periods(scenario: Scenario) -> None:
    """Refuse a scenario whose period lies outside the horizon or is seen before 1.

    Periods lie from 1 to the horizon, and no disruption is seen before period 1.

    Args:
        scenario (Scenario): The scenario.

    Raises:
        InputError: If a period is outside the horizon, at the first one.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Disruption
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="capacity_cut",
        ...     target=None,
        ...     start=6,
        ...     duration=1,
        ...     effect=Decimal("0.5"),
        ... )
        >>> scenario = Scenario(horizon=4, disruptions=(cut,))
        >>> check_periods(scenario)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        disruptions.0.start: is not from 1 to the horizon
    """
    horizon = scenario.horizon
    for position, disruption in enumerate(scenario.disruptions):
        if not 1 <= disruption.start <= horizon:
            raise InputError(
                f"disruptions.{position}.start: is not from 1 to the horizon"
            )
        if disruption.start - disruption.notice < 1:
            raise InputError(
                f"disruptions.{position}.notice: is visible before period 1"
            )
    for position, rule in enumerate(scenario.random_disruptions):
        if rule.start is None:
            continue
        if not 1 <= rule.start <= horizon:
            raise InputError(
                f"random_disruptions.{position}.start: is not from 1 to the horizon"
            )
        if rule.start - rule.notice < 1:
            raise InputError(
                f"random_disruptions.{position}.notice: is visible before period 1"
            )
    for position, order in enumerate(scenario.start.customer_orders):
        if not 1 <= order.due <= horizon:
            raise InputError(
                f"start.customer_orders.{position}.due: is not from 1 to the horizon"
            )
    for position, order in enumerate(scenario.start.supplier_orders):
        if not 1 <= order.arrival <= horizon:
            raise InputError(
                f"start.supplier_orders.{position}.arrival: "
                "is not from 1 to the horizon"
            )


def check_starting_space(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario whose starting stock and orders do not fit their warehouses.

    Each warehouse holds only the items it accepts, and their space fits in it.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If a warehouse does not accept an item or order, at the first
            one; if they do not fit in a warehouse, at the stock of the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Material,
        ...     Warehouse,
        ... )
        >>> from factory_simulator.engine.models.scenario import Start
        >>> zero = Decimal(0)
        >>> steel = Material(space=Decimal(1), storage_cost=zero, salvage_value=zero)
        >>> main = Warehouse(capacity=Decimal(10))
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     warehouses={"main": main},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     cash=cash,
        ... )
        >>> start = Start(stock={"main": {"steel": Decimal(12)}})
        >>> scenario = Scenario(horizon=4, start=start)
        >>> check_starting_space(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        start.stock.main: takes more space than the warehouse has
    """
    items = items_of(factory)
    start = scenario.start
    for warehouse_id, stock in start.stock.items():
        for item_id in stock:
            if not is_accepted(warehouse_id, item_id, factory):
                raise InputError(
                    f"start.stock.{warehouse_id}.{item_id}: "
                    "is not accepted by the warehouse"
                )
    orders = [
        (position, order, order.warehouse or next(iter(factory.warehouses)))
        for position, order in enumerate(start.supplier_orders)
    ]
    for position, order, warehouse_id in orders:
        if not is_accepted(warehouse_id, order.material, factory):
            raise InputError(
                f"start.supplier_orders.{position}.warehouse: "
                "does not accept the material"
            )
    for warehouse_id, warehouse in factory.warehouses.items():
        stock = start.stock.get(warehouse_id, {})
        held = sum(
            (quantity * items[item_id].space for item_id, quantity in stock.items()),
            Decimal(0),
        ) + sum(
            (
                order.quantity * items[order.material].space
                for _, order, ordered_to in orders
                if ordered_to == warehouse_id
            ),
            Decimal(0),
        )
        if held > warehouse.capacity:
            raise InputError(
                f"start.stock.{warehouse_id}: takes more space than the warehouse has"
            )


def check_forecasts(scenario: Scenario, factory: Factory) -> None:
    """Refuse two forecast entries for a customer product or one past the horizon.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory, which names the customer products.

    Raises:
        InputError: If an entry targets a customer product of an earlier entry, at
            the target of the first one; if `periods_ahead` is above the horizon, at it.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Forecast
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> forecast = Forecast(
        ...     customer=None,
        ...     product=None,
        ...     periods_ahead=6,
        ...     noise=Decimal("0.1"),
        ...     noise_growth=Decimal("0.05"),
        ... )
        >>> scenario = Scenario(horizon=4, forecasts=(forecast,))
        >>> check_forecasts(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        forecasts.0.periods_ahead: is above the horizon
    """
    targeted: set[tuple[str, str]] = set()
    for position, entry in enumerate(scenario.forecasts):
        customer_products = {
            (customer_id, product_id)
            for customer_id, customer in factory.customers.items()
            for product_id in customer.products
            if is_customer_product_targeted(entry, customer_id, product_id, factory)
        }
        if customer_products & targeted:
            raise InputError(
                f"forecasts.{position}.target: targets a pair of an earlier entry"
            )
        targeted |= customer_products
        if entry.periods_ahead > scenario.horizon:
            raise InputError(
                f"forecasts.{position}.periods_ahead: is above the horizon"
            )


def check_price_changes(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario in which a price change takes a price below its floors.

    A floor is the salvage value of the material and the cancellation fee of each
    catalogue entry of it. A random price change counts with the smallest factor of
    its range.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If the lowest price of a material, times every price change
            below 1, falls below its salvage value, at the factor of the first such
            change; if the price of an entry is below its largest cancellation fee,
            at that price.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Material,
        ...     Supplier,
        ... )
        >>> from factory_simulator.engine.models.scenario import Disruption
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="price_change",
        ...     target=None,
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("0.4"),
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(
        ...     space=Decimal(1), storage_cost=zero, salvage_value=Decimal(1)
        ... )
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     components={},
        ...     products={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> scenario = Scenario(horizon=4, disruptions=(cut,))
        >>> check_price_changes(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        disruptions.0.factor: takes the price of steel below its salvage value
    """
    for material_id, material in factory.materials.items():
        cuts = [
            (f"disruptions.{position}.factor", disruption.effect)
            for position, disruption in enumerate(scenario.disruptions)
            if disruption.kind == "price_change"
            and disruption.effect < 1
            and material_id
            in targets_in(disruption.kind, disruption.target, disruption.group, factory)
        ] + [
            (f"random_disruptions.{position}.factor", smallest(rule.effect))
            for position, rule in enumerate(scenario.random_disruptions)
            if rule.kind == "price_change"
            and smallest(rule.effect) < 1
            and material_id in targets_in(rule.kind, rule.target, rule.group, factory)
        ]
        if not cuts:
            continue
        cut = Decimal(1)
        for _, factor in cuts:
            cut *= factor
        path = cuts[0][0]
        entries = [
            supplier.catalogue[material_id]
            for supplier in factory.suppliers.values()
            if material_id in supplier.catalogue
        ]
        lowest = min(lowest_price(entry) for entry in entries)
        if lowest * cut < largest(material.salvage_value):
            raise InputError(
                f"{path}: takes the price of {material_id} below its salvage value"
            )
        for entry in entries:
            if lowest_price(entry) * cut < largest(entry.cancellation_fee):
                raise InputError(
                    f"{path}: takes the price of {material_id} below its "
                    "cancellation fee"
                )


def check_materials_arrive(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario in which a material of a recipe cannot be had in the horizon.

    A material can be had when it is in the starting stock, on a starting supplier
    order, or arrives from a supplier before the horizon. The lead time of an entry is
    its `express_lead_time` when given, otherwise its `lead_time`, at its largest.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If a material cannot be had, at `horizon`, for the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     MadeItem,
        ...     Supplier,
        ... )
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=4,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ... )
        >>> zero = Decimal(0)
        >>> rod = MadeItem(
        ...     space=zero,
        ...     storage_cost=zero,
        ...     salvage_value=zero,
        ...     recipes={"cut": {"steel": Decimal(1)}},
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     components={"rod": rod},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     materials={},
        ...     products={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> scenario = Scenario(horizon=4)
        >>> check_materials_arrive(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        horizon: steel cannot arrive within it and is not at hand
    """
    used = {
        material_id
        for component in factory.components.values()
        for recipe in component.recipes.values()
        for material_id in recipe
    }
    for material_id in sorted(used):
        in_stock = any(
            stock.get(material_id, 0) > 0 for stock in scenario.start.stock.values()
        )
        on_order = any(
            order.material == material_id for order in scenario.start.supplier_orders
        )
        entries = [
            supplier.catalogue[material_id]
            for supplier in factory.suppliers.values()
            if material_id in supplier.catalogue
        ]
        fastest = min(
            largest(
                entry.lead_time
                if entry.express_lead_time is None
                else entry.express_lead_time
            )
            for entry in entries
        )
        if not (in_stock or on_order or fastest < scenario.horizon):
            raise InputError(
                f"horizon: {material_id} cannot arrive within it and is not at hand"
            )


@in_decimal_context
def check_amounts(scenario: Scenario, factory: Factory) -> None:
    """Refuse a scenario in which a number of a run can reach 10**24.

    With h the horizon, U the largest units of a period, A the largest amount per
    unit, F the largest changeover or repair cost, r the largest interest rate and S
    the largest space of an item, four bounds stay below 10**24: quantities `U * h`;
    the amount per unit A; money
    `(|cash| + U * h * h * (A * 12 + F * 2 * 1000)) * (1 + r) ** h`, 12 the number of
    kinds of cost and 1000 the changeovers and repairs a unit can pay; space
    `U * h * S` and the capacity of every warehouse.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Raises:
        InputError: If a bound reaches 10**24, at `horizon`.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Material
        >>> zero = Decimal(0)
        >>> steel = Material(space=Decimal(1), storage_cost=zero, salvage_value=zero)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> from factory_simulator.engine.models.scenario import Start
        >>> start = Start(cash=Decimal(10) ** 24)
        >>> scenario = Scenario(horizon=1, start=start)
        >>> check_amounts(scenario, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        horizon: a run of this scenario can exceed the numbers the record holds
    """
    horizon = scenario.horizon
    units = largest_units(scenario, factory)
    amount = largest_amount(scenario, factory)
    per_period = (
        amount * COST_KIND_COUNT
        + largest_fixed_cost(scenario, factory) * 2 * DECISIONS_PER_UNIT
    )
    money = (abs(scenario.start.cash) + units * horizon * horizon * per_period) * (
        1 + largest_rate(factory)
    ) ** horizon
    largest_space = max(item.space for item in items_of(factory).values())
    capacity = max(
        (largest(warehouse.capacity) for warehouse in factory.warehouses.values()),
        default=Decimal(0),
    )
    space = max(units * horizon * largest_space, capacity)
    if max(units * horizon, amount, money, space) >= TOO_LARGE:
        raise InputError(
            "horizon: a run of this scenario can exceed the numbers the record holds"
        )


def largest_units(scenario: Scenario, factory: Factory) -> Decimal:
    """Give a bound of the units of every kind a period can hold.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Returns:
        Decimal: The sum of the largest demand, buys, hours, space and start.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Material,
        ...     Warehouse,
        ... )
        >>> from factory_simulator.engine.models.scenario import Start
        >>> zero = Decimal(0)
        >>> steel = Material(space=Decimal(1), storage_cost=zero, salvage_value=zero)
        >>> main = Warehouse(capacity=Decimal(100))
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     warehouses={"main": main},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     cash=cash,
        ... )
        >>> start = Start(stock={"main": {"steel": Decimal(10)}})
        >>> largest_units(Scenario(horizon=4, start=start), factory)
        Decimal('110')
    """
    demand = sum(
        (
            largest(terms.demand)
            * largest_demand_factor(customer_id, product_id, scenario, factory)
            for customer_id, customer in factory.customers.items()
            for product_id, terms in customer.products.items()
        ),
        Decimal(0),
    )
    buys = sum(
        (
            largest(entry.max_quantity)
            for supplier in factory.suppliers.values()
            for entry in supplier.catalogue.values()
        ),
        Decimal(0),
    )
    hours = sum(
        (
            largest(line.capacity) + largest(line.overtime_hours)
            for line in factory.lines.values()
        ),
        Decimal(0),
    )
    items = items_of(factory)
    smallest_space = min(item.space for item in items.values())
    space = sum(
        (largest(warehouse.capacity) for warehouse in factory.warehouses.values()),
        Decimal(0),
    ) / max(smallest_space, Decimal("0.001"))
    start = scenario.start
    started = sum(
        (quantity for stock in start.stock.values() for quantity in stock.values()),
        Decimal(0),
    ) + sum(
        (order.quantity for order in (*start.customer_orders, *start.supplier_orders)),
        Decimal(0),
    )
    return demand + buys + hours + space + started


def largest_demand_factor(
    customer_id: str, product_id: str, scenario: Scenario, factory: Factory
) -> Decimal:
    """Give the largest shape factor of a customer product times every demand shock.

    The factor is the product, over the shapes that target the customer product, of
    the largest factor of each over the horizon, times the largest effect above 1 of
    every demand shock.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        scenario (Scenario): The scenario.
        factory (Factory): The factory, which holds the members of groups.

    Returns:
        Decimal: The factor, at least 0.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
        >>> from factory_simulator.engine.models.scenario import Step
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
        >>> step = Step(customer=None, product=None, period=1, factor=Decimal("0.5"))
        >>> scenario = Scenario(horizon=3, demand_shapes=(step,))
        >>> largest_demand_factor("shop", "bolt", scenario, factory)
        Decimal('0.5')
    """
    result = Decimal(1)
    for shape in scenario.demand_shapes:
        if is_customer_product_targeted(shape, customer_id, product_id, factory):
            result *= max(
                shape_factor(shape, period) for period in range(1, scenario.horizon + 1)
            )
    return result * largest_effect(scenario, "demand_shock")


def largest_amount(scenario: Scenario, factory: Factory) -> Decimal:
    """Give the largest amount of money per unit a run can meet.

    The amount is the largest of: every money parameter times the largest price
    change; every `storage_cost` times the largest `storage_factor`; every
    `transport_cost` times the largest `transport_factor`; the `credit_limit`.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Returns:
        Decimal: The amount.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Material,
        ...     Warehouse,
        ... )
        >>> from factory_simulator.engine.models.scenario import Disruption
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="price_change",
        ...     target=None,
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("1.2"),
        ... )
        >>> steel = Material(
        ...     space=Decimal(1),
        ...     storage_cost=Decimal("0.10"),
        ...     salvage_value=Decimal("0.50"),
        ... )
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> main = Warehouse(capacity=Decimal(100), storage_factor=Decimal(8))
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": main},
        ...     cash=cash,
        ... )
        >>> largest_amount(Scenario(horizon=4, disruptions=(cut,)), factory)
        Decimal('0.80')
    """
    warehouses = factory.warehouses.values()
    storage_factor = max(
        (warehouse.storage_factor for warehouse in warehouses), default=Decimal(0)
    )
    transport_factor = max(
        (warehouse.transport_factor for warehouse in warehouses), default=Decimal(0)
    )
    price_change = largest_effect(scenario, "price_change")
    amounts = [factory.cash.credit_limit]
    for path, value in walk_parameters(factory, ""):
        key = path.rsplit(".", 1)[-1]
        if key not in MONEY_KEYS or not isinstance(value, Decimal | Range):
            continue
        amount = largest(cast(Decimal | Range[Decimal], value))
        amounts.append(amount * price_change)
        if key == "storage_cost":
            amounts.append(amount * storage_factor)
        if key == "transport_cost":
            amounts.append(amount * transport_factor)
    return max(amounts)


def largest_fixed_cost(scenario: Scenario, factory: Factory) -> Decimal:
    """Give the largest changeover or repair cost a run can meet.

    Each cost counts times the largest price change.

    Args:
        scenario (Scenario): The scenario.
        factory (Factory): The factory.

    Returns:
        Decimal: The cost, 0 without a changeover or repair cost.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Line, LineItem
        >>> zero, one = Decimal(0), Decimal(1)
        >>> press = Line(
        ...     capacity=one,
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=Decimal(3),
        ...     repair_time=one,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
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
        ...     lines={"press": press},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> largest_fixed_cost(Scenario(horizon=4), factory)
        Decimal('3')
    """
    price_change = largest_effect(scenario, "price_change")
    costs = [Decimal(0)]
    for path, value in walk_parameters(factory, ""):
        key = path.rsplit(".", 1)[-1]
        if key in ("changeover_cost", "repair_cost") and isinstance(
            value, Decimal | Range
        ):
            costs.append(largest(cast(Decimal | Range[Decimal], value)) * price_change)
    return max(costs)


def largest_effect(scenario: Scenario, kind: str) -> Decimal:
    """Give the largest product of the effects above 1 of the disruptions of a kind.

    Each written disruption and each random rule of the kind counts once.

    Args:
        scenario (Scenario): The scenario.
        kind (str): The kind of disruption.

    Returns:
        Decimal: The product, at least 1.

    Examples:
        >>> from factory_simulator.engine.models.scenario import Disruption
        >>> shock = Disruption(
        ...     id="disruption-1",
        ...     kind="demand_shock",
        ...     target=None,
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("1.5"),
        ... )
        >>> scenario = Scenario(horizon=4, disruptions=(shock, shock))
        >>> largest_effect(scenario, "demand_shock")
        Decimal('2.25')
    """
    result = Decimal(1)
    for disruption in scenario.disruptions:
        if disruption.kind == kind:
            result *= max(Decimal(1), disruption.effect)
    for rule in scenario.random_disruptions:
        if rule.kind == kind:
            result *= max(Decimal(1), largest(rule.effect))
    return result


def largest_rate(factory: Factory) -> Decimal:
    """Give the largest interest rate of the cash of a factory.

    Args:
        factory (Factory): The factory.

    Returns:
        Decimal: The rate.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal("0.01"),
        ...     debit_interest=Decimal("0.02"),
        ...     overdraft_interest=Decimal("0.05"),
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
        >>> largest_rate(factory)
        Decimal('0.05')
    """
    cash = factory.cash
    return max(cash.credit_interest, cash.debit_interest, cash.overdraft_interest)
