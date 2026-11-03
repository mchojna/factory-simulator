"""The world drawn from the seed: parameters, series, deliveries and disruptions.

Examples:
    >>> draw_series(Range(min=Decimal("4.0"), max=Decimal("4.0")), 2, 7, "demand")
    (Decimal('4.0'), Decimal('4.0'))
"""

from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType
from typing import cast

from factory_simulator.engine.draws.forecasts import draw_forecasts
from factory_simulator.engine.draws.streams import draw_uniform, open_stream
from factory_simulator.engine.draws.values import (
    carry_demand_over,
    choose_target,
    combine_demand_draws,
    draw_parameter,
    draw_value,
    is_within_chance,
    raised_chances,
)
from factory_simulator.engine.models.manifest import (
    CatalogueEntry,
    DecimalParameter,
    Factory,
    Line,
    Range,
)
from factory_simulator.engine.models.scenario import (
    Disruption,
    RandomDisruption,
    Scenario,
)
from factory_simulator.engine.models.world import Breakdown, Delivery, World
from factory_simulator.engine.numbers import in_decimal_context
from factory_simulator.engine.rules.parameters import DRAWN_PER_PERIOD, walk_parameters
from factory_simulator.engine.rules.targets import targets_in


@in_decimal_context
def draw_world(factory: Factory, scenario: Scenario, seed: int) -> World:
    """Draw the whole world of a run from the seed.

    Every source of randomness has its own stream, so adding an object changes no
    value drawn for the others.

    Args:
        factory (Factory): The factory.
        scenario (Scenario): The scenario.
        seed (int): The seed, a whole number from 0.

    Returns:
        World: The factory, the scenario and every drawn value.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Customer
        >>> from factory_simulator.engine.models.manifest import CustomerProduct
        >>> zero = Decimal(0)
        >>> demand = Range(min=Decimal("8.000"), max=Decimal("12.000"))
        >>> bolt = CustomerProduct(
        ...     price=zero,
        ...     transport_cost=zero,
        ...     demand=demand,
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
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
        >>> draw_world(factory, Scenario(horizon=2), 0).demand["shop/bolt"]
        (Decimal('11.547'), Decimal('11.998'))
    """
    parameters, drawn = draw_run_parameters(factory, seed)
    horizon = scenario.horizon
    common_draws = {
        product_id: draw_common_demand(horizon, seed, "demand", product_id)
        for product_id in factory.products
    }
    demand = {
        f"{customer_id}/{product_id}": carry_demand_over(
            draw_demand(
                terms.demand,
                common_draws.get(product_id, ()),
                common_share_of(product_id, factory),
                horizon,
                seed,
                "demand",
                customer_id,
                product_id,
            ),
            terms.demand_persistence or Decimal(0),
        )
        for customer_id, customer in factory.customers.items()
        for product_id, terms in customer.products.items()
    }
    deliveries = {
        f"{supplier_id}/{material_id}": draw_deliveries(
            entry,
            parameters[f"suppliers.{supplier_id}.catalogue.{material_id}.punctuality"],
            horizon,
            seed,
            "delivery",
            supplier_id,
            material_id,
        )
        for supplier_id, supplier in factory.suppliers.items()
        for material_id, entry in supplier.catalogue.items()
    }
    express_deliveries = {
        f"{supplier_id}/{material_id}": draw_deliveries(
            entry,
            parameters[f"suppliers.{supplier_id}.catalogue.{material_id}.punctuality"],
            horizon,
            seed,
            "express",
            supplier_id,
            material_id,
        )
        for supplier_id, supplier in factory.suppliers.items()
        for material_id, entry in supplier.catalogue.items()
        if entry.express_lead_time is not None
    }
    yields = {
        f"{line_id}/{item_id}": draw_series(
            terms.yield_, horizon, seed, "yield", line_id, item_id
        )
        for line_id, line in factory.lines.items()
        for item_id, terms in line.items.items()
    }
    breakdowns = {
        line_id: draw_breakdowns(
            line,
            parameters[f"lines.{line_id}.breakdown_chance"],
            horizon,
            seed,
            "breakdown",
            line_id,
        )
        for line_id, line in factory.lines.items()
    }
    prices = {
        f"{supplier_id}/{material_id}": draw_series(
            entry.price,
            horizon,
            seed,
            "parameter",
            f"suppliers.{supplier_id}.catalogue.{material_id}.price",
        )
        for supplier_id, supplier in factory.suppliers.items()
        for material_id, entry in supplier.catalogue.items()
        if isinstance(entry.price, Range) and entry.price.drawn == "period"
    }
    world = World(
        factory=factory,
        scenario=scenario,
        disruptions=(
            *scenario.disruptions,
            *draw_random_disruptions(factory, scenario, seed),
        ),
        parameters=MappingProxyType(parameters),
        drawn=drawn,
        demand=MappingProxyType(demand),
        deliveries=MappingProxyType(deliveries),
        yields=MappingProxyType(yields),
        breakdowns=MappingProxyType(breakdowns),
        prices=MappingProxyType(prices),
        express_deliveries=MappingProxyType(express_deliveries),
    )
    forecasts, forecast_errors = draw_forecasts(world, seed)
    return replace(world, forecasts=forecasts, forecast_errors=forecast_errors)


def draw_run_parameters(
    factory: Factory, seed: int
) -> tuple[dict[str, Decimal], frozenset[str]]:
    """Draw every parameter drawn once per run and take every fixed one.

    A price drawn once per period is left to `draw_world`.

    Args:
        factory (Factory): The factory.
        seed (int): The seed.

    Returns:
        tuple[dict[str, Decimal], frozenset[str]]: The value of each parameter by its
            dotted path, and the paths of those drawn from a range.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Customer
        >>> from factory_simulator.engine.models.manifest import CustomerProduct
        >>> zero = Decimal(0)
        >>> price = Range(min=Decimal("5.00"), max=Decimal("5.00"))
        >>> bolt = CustomerProduct(
        ...     price=price,
        ...     transport_cost=zero,
        ...     demand=Decimal("10.000"),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
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
        >>> parameters, drawn = draw_run_parameters(factory, 0)
        >>> parameters["customers.shop.products.bolt.price"], sorted(drawn)
        (Decimal('5.00'), ['customers.shop.products.bolt.price'])
    """
    parameters: dict[str, Decimal] = {}
    drawn: set[str] = set()
    for path, value in walk_parameters(factory, ""):
        if path.rsplit(".", 1)[-1] in DRAWN_PER_PERIOD:
            continue
        if isinstance(value, Range) and value.drawn == "period":
            continue
        if isinstance(value, Range):
            stream = open_stream(seed, "parameter", path)
            parameters[path] = draw_parameter(cast(Range[Decimal], value), stream)
            drawn.add(path)
        elif isinstance(value, Decimal | int) and not isinstance(value, bool):
            parameters[path] = Decimal(value)
    return parameters, frozenset(drawn)


def draw_series(
    value: DecimalParameter, horizon: int, seed: int, *key: str
) -> tuple[Decimal, ...]:
    """Draw one value of a parameter for every period from 1 to the horizon.

    Args:
        value (Decimal | Range[Decimal]): A fixed number or a range.
        horizon (int): Number of periods.
        seed (int): The seed.
        *key (str): The parts of the key of the stream.

    Returns:
        tuple[Decimal, ...]: One value per period.

    Examples:
        >>> draw_series(Decimal("10.000"), 3, 0, "demand", "shop", "bolt")
        (Decimal('10.000'), Decimal('10.000'), Decimal('10.000'))
    """
    stream = open_stream(seed, *key)
    return tuple(draw_parameter(value, stream) for _ in range(horizon))


def draw_common_demand(horizon: int, seed: int, *key: str) -> tuple[Decimal, ...]:
    """Draw the common uniform number of a product for every period.

    Args:
        horizon (int): Number of periods.
        seed (int): The seed.
        *key (str): The parts of the key of the stream, `demand, <product>`.

    Returns:
        tuple[Decimal, ...]: One uniform number per period.

    Examples:
        >>> len(draw_common_demand(3, 0, "demand", "bolt"))
        3
    """
    stream = open_stream(seed, *key)
    return tuple(draw_uniform(stream) for _ in range(horizon))


def common_share_of(product_id: str, factory: Factory) -> Decimal:
    """Give the common share of a product, 0 when the manifest leaves it out.

    Args:
        product_id (str): The identifier of the product.
        factory (Factory): The factory.

    Returns:
        Decimal: The share, from 0 to 1.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> common_share_of("bolt", factory)
        Decimal('0')
    """
    product = factory.products.get(product_id)
    if product is None or product.common_share is None:
        return Decimal(0)
    return product.common_share


def draw_demand(
    value: DecimalParameter,
    common_draws: tuple[Decimal, ...],
    common_share: Decimal,
    horizon: int,
    seed: int,
    *key: str,
) -> tuple[Decimal, ...]:
    """Draw the demand of one customer product for every period, before persistence.

    With a common share of 0 the stream of the customer product draws the demand as a
    series. Otherwise each period mixes the common draw of the product into the own
    draw of the customer product with `combine_demand_draws` and draws the demand
    with the result.

    Args:
        value (Decimal | Range[Decimal]): The demand, a fixed number or a range.
        common_draws (tuple[Decimal, ...]): The common draw of the product per period.
        common_share (Decimal): The common share of the product.
        horizon (int): Number of periods.
        seed (int): The seed.
        *key (str): The parts of the key of the stream,
            `demand, <customer>, <product>`.

    Returns:
        tuple[Decimal, ...]: One demand per period.

    Examples:
        >>> draw_demand(
        ...     Decimal("10.000"), (), Decimal(0), 2, 0, "demand", "shop", "bolt"
        ... )
        (Decimal('10.000'), Decimal('10.000'))
    """
    if common_share == 0:
        return draw_series(value, horizon, seed, *key)
    stream = open_stream(seed, *key)
    demand: list[Decimal] = []
    for common in common_draws:
        own = draw_uniform(stream)
        if isinstance(value, Decimal):
            demand.append(value)
            continue
        uniform = combine_demand_draws(common, own, common_share)
        demand.append(draw_value(value, uniform))
    return tuple(demand)


def draw_deliveries(
    entry: CatalogueEntry,
    punctuality: Decimal,
    horizon: int,
    seed: int,
    *key: str,
) -> tuple[Delivery, ...]:
    """Draw the delivery outcome of every placing period of one catalogue entry.

    Args:
        entry (CatalogueEntry): The catalogue entry.
        punctuality (Decimal): Its punctuality, drawn once per run.
        horizon (int): Number of periods.
        seed (int): The seed.
        *key (str): The parts of the key of the stream.

    Returns:
        tuple[Delivery, ...]: One outcome per placing period.

    Examples:
        >>> one = Decimal(1)
        >>> entry = CatalogueEntry(
        ...     price=one,
        ...     lead_time=1,
        ...     max_quantity=one,
        ...     punctuality=one,
        ...     delay=0,
        ...     completeness=one,
        ...     acceptance=one,
        ... )
        >>> half = Decimal("0.5")
        >>> drawn = draw_deliveries(entry, half, 4, 0, "delivery", "mill", "rod")
        >>> [delivery.punctual for delivery in drawn]
        [True, False, True, True]
    """
    stream = open_stream(seed, *key)
    deliveries: list[Delivery] = []
    for period in range(1, horizon + 1):
        punctual = is_within_chance(punctuality, draw_uniform(stream))
        delay = int(draw_parameter(entry.delay, stream))
        completeness = draw_parameter(entry.completeness, stream)
        acceptance = draw_parameter(entry.acceptance, stream)
        deliveries.append(
            Delivery(
                period=period,
                punctual=punctual,
                delay=delay,
                completeness=completeness,
                acceptance=acceptance,
            )
        )
    return tuple(deliveries)


def draw_breakdowns(
    line: Line, chance: Decimal, horizon: int, seed: int, *key: str
) -> tuple[Breakdown, ...]:
    """Draw whether a line breaks down, and its loss, in every period.

    Args:
        line (Line): The line.
        chance (Decimal): Its breakdown chance, drawn once per run.
        horizon (int): Number of periods.
        seed (int): The seed.
        *key (str): The parts of the key of the stream.

    Returns:
        tuple[Breakdown, ...]: One breakdown draw per period.

    Examples:
        >>> zero = Decimal(0)
        >>> line = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=Decimal("0.1"),
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=Decimal(1),
        ...     items={},
        ... )
        >>> drawn = draw_breakdowns(line, Decimal(1), 2, 0, "breakdown", "press")
        >>> [breakdown.breaks for breakdown in drawn]
        [True, True]
    """
    stream = open_stream(seed, *key)
    breakdowns: list[Breakdown] = []
    for period in range(1, horizon + 1):
        breaks = is_within_chance(chance, draw_uniform(stream))
        loss = draw_parameter(line.breakdown_loss, stream)
        breakdowns.append(Breakdown(period=period, breaks=breaks, loss=loss))
    return tuple(breakdowns)


def draw_random_disruptions(
    factory: Factory, scenario: Scenario, seed: int
) -> tuple[Disruption, ...]:
    """Draw the disruptions every rule of the scenario starts.

    The stream `disruption, <name>, <target>` of each target draws, in every period,
    a start draw (a target draw with `choose: one` or a written start), the duration
    but for a line breakdown, then the effect. With `choose: one` the stream
    `disruption, <name>` draws the start of the period. A rule with a written start
    starts one disruption, in that period, on the target with the smallest draw. A
    rule keeps every start it draws, but none on a target it still acts on; the draws
    of that period are drawn all the same. A start in a period up to `notice` is
    visible from period 1. The rules no cascade names are drawn first; a named rule
    then compares its start draws with its chance raised after every start of the
    rules that name it.

    Args:
        factory (Factory): The factory, which names the targets.
        scenario (Scenario): The scenario.
        seed (int): The seed.

    Returns:
        tuple[Disruption, ...]: The drawn disruptions by name, start and target.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
        >>> from factory_simulator.engine.models.scenario import RandomDisruption
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
        >>> strike = RandomDisruption(
        ...     name="strike",
        ...     kind="supplier_outage",
        ...     target=("mill",),
        ...     chance=Decimal(1),
        ...     duration=2,
        ...     effect=Decimal(1),
        ... )
        >>> scenario = Scenario(horizon=3, random_disruptions=(strike,))
        >>> started = draw_random_disruptions(factory, scenario, 0)
        >>> [disruption.id for disruption in started]
        ['strike/1/mill', 'strike/3/mill']
    """
    rules = scenario.random_disruptions
    named = {rule.raises.rule for rule in rules if rule.raises is not None}
    starts: dict[str, list[int]] = {}
    started: list[Disruption] = []
    for rule in sorted(rules, key=lambda rule: rule.name in named):
        windows = [
            (start, raising.raises)
            for raising in rules
            if raising.raises is not None and raising.raises.rule == rule.name
            for start in starts[raising.name]
        ]
        chances = raised_chances(rule.chance or Decimal(0), windows, scenario.horizon)
        drawn = draw_rule_disruptions(rule, chances, factory, seed)
        starts[rule.name] = [disruption.start for disruption in drawn]
        started.extend(drawn)
    return tuple(
        sorted(
            started,
            key=lambda disruption: (
                cast(str, disruption.rule),
                disruption.start,
                disruption.target,
            ),
        )
    )


def draw_rule_disruptions(
    rule: RandomDisruption, chances: tuple[Decimal, ...], factory: Factory, seed: int
) -> tuple[Disruption, ...]:
    """Draw the disruptions one rule starts, with its chance of every period.

    Args:
        rule (RandomDisruption): The rule.
        chances (tuple[Decimal, ...]): The chance of a start in periods 1 to the
            horizon.
        factory (Factory): The factory, which names the targets.
        seed (int): The seed.

    Returns:
        tuple[Disruption, ...]: The drawn disruptions, by start and target.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> strike = RandomDisruption(
        ...     name="strike",
        ...     kind="supplier_outage",
        ...     target=("mill",),
        ...     chance=Decimal(1),
        ...     duration=1,
        ...     effect=Decimal(1),
        ... )
        >>> drawn = draw_rule_disruptions(strike, (Decimal(0), Decimal(1)), factory, 0)
        >>> [disruption.id for disruption in drawn]
        ['strike/2/mill']
    """
    targets = targets_in(rule.kind, rule.target, rule.group, factory)
    streams = {
        target: open_stream(seed, "disruption", rule.name, target) for target in targets
    }
    rule_stream = open_stream(seed, "disruption", rule.name)
    ends: dict[str, int] = {}
    started: list[Disruption] = []
    for period, chance in enumerate(chances, start=1):
        rule_start = draw_uniform(rule_stream) if rule.choose else Decimal(0)
        slots: dict[str, tuple[Decimal, int, Decimal]] = {}
        for target in targets:
            first = draw_uniform(streams[target])
            duration = (
                1
                if rule.duration is None
                else int(draw_parameter(rule.duration, streams[target]))
            )
            effect = draw_parameter(rule.effect, streams[target])
            slots[target] = (first, duration, effect)
        if rule.start is not None:
            hit = choose_target({target: slot[0] for target, slot in slots.items()})
            starting = [hit] if period == rule.start else []
        elif rule.choose:
            hit = choose_target({target: slot[0] for target, slot in slots.items()})
            starting = [hit] if is_within_chance(chance, rule_start) else []
        else:
            starting = [
                target
                for target in targets
                if is_within_chance(chance, slots[target][0])
            ]
        for target in starting:
            if ends.get(target, 0) >= period:
                continue
            _, duration, effect = slots[target]
            ends[target] = period + duration - 1
            started.append(
                Disruption(
                    id=f"{rule.name}/{period}/{target}",
                    kind=rule.kind,
                    target=(target,),
                    start=period,
                    duration=duration,
                    effect=effect,
                    notice=rule.notice,
                    rule=rule.name,
                )
            )
    return tuple(started)
