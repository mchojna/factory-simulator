"""The demand shapes of a scenario: the factor of demand of a customer product.

Examples:
    >>> shape_factor(Step(customer=None, product=None, period=3, factor=Decimal(2)), 4)
    Decimal('2')
"""

from decimal import Decimal

from factory_simulator.engine.models.manifest import Factory
from factory_simulator.engine.models.scenario import (
    DemandShape,
    Ramp,
    Scenario,
    SCurve,
    Season,
    Step,
    Trend,
)
from factory_simulator.engine.numbers import in_decimal_context
from factory_simulator.engine.rules.targets import is_customer_product_targeted


@in_decimal_context
def demand_factor(
    customer_id: str, product_id: str, period: int, scenario: Scenario, factory: Factory
) -> Decimal:
    """Give the product of the factors of the shapes that target a customer product.

    The factors are those of one period. A shape targeting a group of customers
    targets every customer product whose customer is a member; one targeting a group
    of products, every customer product whose product is.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        period (int): The period.
        scenario (Scenario): The scenario.
        factory (Factory): The factory, which holds the members of groups.

    Returns:
        Decimal: The factor, 1 when no shape targets the customer product.

    Examples:
        >>> from factory_simulator.engine import Cash
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
        >>> step = Step(customer="shop", product=None, period=3, factor=Decimal(2))
        >>> scenario = Scenario(horizon=4, demand_shapes=(step,))
        >>> demand_factor("shop", "bolt", 4, scenario, factory)
        Decimal('2')
    """
    result = Decimal(1)
    for shape in scenario.demand_shapes:
        if is_customer_product_targeted(shape, customer_id, product_id, factory):
            result *= shape_factor(shape, period)
    return result


def shape_factor(shape: DemandShape, period: int) -> Decimal:
    """Give the factor of one demand shape in a period.

    With t the period, the factor of each kind of shape is:

    - trend: `(1 + rate) ** (t - 1)`;
    - season: `factors[((t - 1) // period_length) % len(factors)]`;
    - step: `factor` from `period` on, else 1;
    - ramp: `from_factor` up to `first`, `to_factor` from `last`, a straight line
      between;
    - s-curve:
      `from_factor + (to_factor - from_factor) / (1 + exp(-steepness * (t - middle)))`.

    Args:
        shape (Trend | Season | Step | Ramp | SCurve): The shape.
        period (int): The period.

    Returns:
        Decimal: The factor.

    Examples:
        >>> shape_factor(Trend(customer=None, product=None, rate=Decimal("0.01")), 3)
        Decimal('1.0201')
        >>> ramp = Ramp(
        ...     customer=None,
        ...     product=None,
        ...     first=2,
        ...     last=6,
        ...     from_factor=Decimal(1),
        ...     to_factor=Decimal(2),
        ... )
        >>> shape_factor(ramp, 4)
        Decimal('1.5')
    """
    match shape:
        case Trend():
            return (1 + shape.rate) ** (period - 1)
        case Season():
            index = ((period - 1) // shape.period_length) % len(shape.factors)
            return shape.factors[index]
        case Step():
            return shape.factor if period >= shape.period else Decimal(1)
        case Ramp():
            if period <= shape.first:
                return shape.from_factor
            if period >= shape.last:
                return shape.to_factor
            share = Decimal(period - shape.first) / (shape.last - shape.first)
            return shape.from_factor + (shape.to_factor - shape.from_factor) * share
        case SCurve():
            # Far before the middle the exponent overflows to Infinity, which the
            # decimal context allows, and the factor is `from_factor`.
            exponent = (-shape.steepness * (period - shape.middle)).exp()
            rise = (shape.to_factor - shape.from_factor) / (1 + exponent)
            return shape.from_factor + rise
