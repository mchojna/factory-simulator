"""The forecasts of demand: their errors, drawn before period 1, and quantities.

Examples:
    >>> forecast_quantity(Decimal("50.000"), Decimal("-0.0800"))
    Decimal('46.000')
"""

from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.draws.streams import draw_uniform, open_stream
from factory_simulator.engine.models.scenario import Disruption, Forecast
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import in_decimal_context, round_to
from factory_simulator.engine.rules.demand import demand_factor
from factory_simulator.engine.rules.disruptions import is_active, is_visible
from factory_simulator.engine.rules.targets import (
    is_customer_product_targeted,
    targets_of,
)

# The forecasts made in each period, per targeted `<customer>/<product>`.
type Forecasts = MappingProxyType[str, tuple[tuple[Decimal | None, ...], ...]]
# The error of each of those forecasts.
type ForecastErrors = MappingProxyType[str, tuple[tuple[Decimal | None, ...], ...]]


@in_decimal_context
def draw_forecast_increment(width: Decimal, uniform: Decimal) -> Decimal:
    """Draw one increment of the error of a forecast.

    Args:
        width (Decimal): The width of the increment: `noise` for distance 1,
            `noise_growth` for every further distance.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        Decimal: `-width + 2 * width * uniform`, rounded half to even to 4 places.

    Examples:
        >>> draw_forecast_increment(Decimal("0.1000"), Decimal("0.7068"))
        Decimal('0.0414')
    """
    return round_to(-width + 2 * width * uniform, 4)


@in_decimal_context
def forecast_quantity(demand: Decimal, error: Decimal) -> Decimal:
    """Give a forecast of a demand with its error.

    Args:
        demand (Decimal): The demand known when the forecast is made.
        error (Decimal): The error e.

    Returns:
        Decimal: `demand * (1 + e)`, rounded half to even to 3 places, 0 with a
            positive sign when it is not above 0.

    Examples:
        >>> forecast_quantity(Decimal("50.000"), Decimal("-0.0800"))
        Decimal('46.000')
        >>> forecast_quantity(Decimal("0.000"), Decimal("-1.2000"))
        Decimal('0.000')
    """
    quantity = round_to(demand * (1 + error), 3)
    if quantity > 0:
        return quantity
    return Decimal("0.000")


def forecast_of(customer_id: str, product_id: str, world: World) -> Forecast | None:
    """Give the forecast entry that targets a customer product.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        world (World): The world.

    Returns:
        Forecast | None: The entry, or None when no entry targets the customer
            product.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> bolt = CustomerProduct(
        ...     price=zero,
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
        >>> entry = Forecast(
        ...     customer="shop",
        ...     product="bolt",
        ...     periods_ahead=1,
        ...     noise=zero,
        ...     noise_growth=zero,
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2, forecasts=(entry,)), 0)
        >>> forecast_of("shop", "bolt", world).periods_ahead
        1
    """
    for entry in world.scenario.forecasts:
        if is_customer_product_targeted(entry, customer_id, product_id, world.factory):
            return entry
    return None


@in_decimal_context
def shaped_demand(
    customer_id: str, product_id: str, world: World
) -> tuple[Decimal, ...]:
    """Give the base demand of a customer product times its shape factor, per period.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        world (World): The world.

    Returns:
        tuple[Decimal, ...]: The demand of each period from 1 to the horizon, not
            rounded.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> bolt = CustomerProduct(
        ...     price=zero,
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
        >>> world = draw_world(factory, Scenario(horizon=2), 0)
        >>> shaped_demand("shop", "bolt", world)
        (Decimal('10.000'), Decimal('10.000'))
    """
    base = world.demand[f"{customer_id}/{product_id}"]
    return tuple(
        base[period - 1]
        * demand_factor(customer_id, product_id, period, world.scenario, world.factory)
        for period in range(1, world.scenario.horizon + 1)
    )


def demand_shocks(product_id: str, world: World) -> tuple[Disruption, ...]:
    """Give the demand shocks that act on a product and may enter its forecasts.

    A shock in a forecast would show when it ends, so a hidden duration keeps every
    shock out.

    Args:
        product_id (str): The identifier of the product.
        world (World): The world.

    Returns:
        tuple[Disruption, ...]: The shocks, written then drawn.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> bolt = CustomerProduct(
        ...     price=zero,
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
        >>> shock = Disruption(
        ...     id="disruption-1",
        ...     kind="demand_shock",
        ...     target=("bolt",),
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("2"),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2, disruptions=(shock,)), 0)
        >>> [disruption.id for disruption in demand_shocks("bolt", world)]
        ['disruption-1']
    """
    if "disruptions.duration" in world.scenario.hidden:
        return ()
    return tuple(
        disruption
        for disruption in world.disruptions
        if disruption.kind == "demand_shock"
        and product_id in targets_of(disruption, world)
    )


@in_decimal_context
def known_demand(
    shaped: tuple[Decimal, ...], shocks: tuple[Disruption, ...], made: int, period: int
) -> Decimal:
    """Give the demand of a customer product in a period as known in an earlier one.

    It is the shaped demand times the factor of every demand shock that is visible
    when the forecast is made and acts in the period.

    Args:
        shaped (tuple[Decimal, ...]): The shaped demand of the customer product, from
            `shaped_demand`.
        shocks (tuple[Disruption, ...]): Its demand shocks, from `demand_shocks`.
        made (int): The period the forecast is made.
        period (int): The period it is made for.

    Returns:
        Decimal: The demand, rounded half to even to 3 places.

    Examples:
        >>> shock = Disruption(
        ...     id="disruption-1",
        ...     kind="demand_shock",
        ...     target=("bolt",),
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("2"),
        ... )
        >>> shaped = (Decimal("10.000"), Decimal("10.000"))
        >>> known_demand(shaped, (shock,), 1, 2)
        Decimal('10.000')
        >>> known_demand(shaped, (shock,), 2, 2)
        Decimal('20.000')
    """
    shock = Decimal(1)
    for disruption in shocks:
        if is_visible(disruption, made) and is_active(disruption, period):
            shock *= disruption.effect
    return round_to(shaped[period - 1] * shock, 3)


def draw_forecasts(world: World, seed: int) -> tuple[Forecasts, ForecastErrors]:
    """Draw the error of every forecast and make every forecast of a customer product.

    The stream `forecast, <customer>, <product>, <j>` of each distance j from 1 to
    `periods_ahead` draws one increment `i_j(P)` for each target period P from 1 to
    the horizon, within `noise` for j = 1 and `noise_growth` after. The forecast made
    in t for P = t + k has the error `i_1(P) + ... + i_k(P)`; a forecast past the
    horizon has none.

    Args:
        world (World): The world, its forecasts not yet made.
        seed (int): The seed.

    Returns:
        tuple[MappingProxyType[str, tuple[tuple[Decimal | None, ...], ...]],
            MappingProxyType[str, tuple[tuple[Decimal | None, ...], ...]]]: The
            forecasts and their errors, each per `<customer>/<product>` and period
            t, None past the horizon.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> bolt = CustomerProduct(
        ...     price=zero,
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
        >>> entry = Forecast(
        ...     customer="shop",
        ...     product="bolt",
        ...     periods_ahead=1,
        ...     noise=zero,
        ...     noise_growth=zero,
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2, forecasts=(entry,)), 0)
        >>> forecasts, _ = draw_forecasts(world, 0)
        >>> forecasts["shop/bolt"]
        ((Decimal('10.000'),), (None,))
    """
    horizon = world.scenario.horizon
    forecasts: dict[str, tuple[tuple[Decimal | None, ...], ...]] = {}
    errors: dict[str, tuple[tuple[Decimal | None, ...], ...]] = {}
    for customer_id, customer in sorted(world.factory.customers.items()):
        for product_id in sorted(customer.products):
            entry = forecast_of(customer_id, product_id, world)
            if entry is None:
                continue
            increments: dict[int, list[Decimal]] = {}
            for distance in range(1, entry.periods_ahead + 1):
                stream = open_stream(
                    seed, "forecast", customer_id, product_id, str(distance)
                )
                width = entry.noise if distance == 1 else entry.noise_growth
                increments[distance] = [
                    draw_forecast_increment(width, draw_uniform(stream))
                    for _ in range(horizon)
                ]
            shaped = shaped_demand(customer_id, product_id, world)
            shocks = demand_shocks(product_id, world)
            made_rows: list[tuple[Decimal | None, ...]] = []
            error_rows: list[tuple[Decimal | None, ...]] = []
            for made in range(1, horizon + 1):
                row: list[Decimal | None] = []
                error_row: list[Decimal | None] = []
                for ahead in range(1, entry.periods_ahead + 1):
                    period = made + ahead
                    if period > horizon:
                        row.append(None)
                        error_row.append(None)
                        continue
                    error = sum(
                        (increments[j][period - 1] for j in range(1, ahead + 1)),
                        Decimal(0),
                    )
                    error_row.append(error)
                    demand = known_demand(shaped, shocks, made, period)
                    row.append(forecast_quantity(demand, error))
                made_rows.append(tuple(row))
                error_rows.append(tuple(error_row))
            key = f"{customer_id}/{product_id}"
            forecasts[key] = tuple(made_rows)
            errors[key] = tuple(error_rows)
    return MappingProxyType(forecasts), MappingProxyType(errors)
