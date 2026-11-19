"""The economic profile of a generated manifest: lowest costs, margins and coverage.

Examples:
    >>> from factory_simulator.engine.generation import generate_manifest
    >>> counts = {
    ...     "materials": 1,
    ...     "components": 1,
    ...     "products": 1,
    ...     "suppliers": 1,
    ...     "customers": 1,
    ...     "lines": 1,
    ... }
    >>> profile = build_economic_profile(generate_manifest(counts, 0))
    >>> profile.economic_class
    'profitable'
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from factory_simulator.engine.numbers import InputError, in_decimal_context, round_to

# A number of a manifest as JSON: text or a decimal, or a range with `min` and `max`.
type Written = str | Decimal | Mapping[str, str | Decimal]


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomerProductProfile:
    """The economics of one unit of a customer product.

    Attributes:
        customer (str): The identifier of the customer.
        product (str): The identifier of the product.
        lowest_cost (Decimal): What one unit of the product costs at best.
        best_margin (Decimal): The price less the transport cost and the lowest cost.
        service_value (Decimal): The most that shipping one unit on time is worth:
            the price less the transport cost, plus the lost-sale penalty and
            patience times the late penalty that it avoids.
        demand (Decimal): The middle of the demand range.

    Examples:
        >>> profile = CustomerProductProfile(
        ...     customer="customer-1",
        ...     product="product-1",
        ...     lowest_cost=Decimal("50"),
        ...     best_margin=Decimal("40"),
        ...     service_value=Decimal("150"),
        ...     demand=Decimal("10"),
        ... )
        >>> profile.best_margin
        Decimal('40')
    """

    customer: str
    product: str
    lowest_cost: Decimal
    best_margin: Decimal
    service_value: Decimal
    demand: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicProfile:
    """The economic profile of a generated manifest.

    Attributes:
        customer_products (tuple[CustomerProductProfile, ...]): Every customer
            product, by customer and then product.
        useful_demand_coverage (Decimal): The share of the middle demand in customer
            products whose service value is above their lowest cost, to 4 places; 0
            when the middle demand is 0.
        margin_share (Decimal): The best margins over the prices, each weighted by
            the middle demand, to 4 places; 0 when the prices so weighted sum to 0.
        economic_class (str): `profitable` when a best margin is above 0,
            `penalty-driven` when none is but a service value is above its lowest
            cost, and `unproductive` otherwise.

    Examples:
        >>> EconomicProfile(
        ...     customer_products=(),
        ...     useful_demand_coverage=Decimal(0),
        ...     margin_share=Decimal(0),
        ...     economic_class="unproductive",
        ... ).economic_class
        'unproductive'
    """

    customer_products: tuple[CustomerProductProfile, ...]
    useful_demand_coverage: Decimal
    margin_share: Decimal
    economic_class: str


def lower_bound(value: Written) -> Decimal:
    """Give the lower bound of a range of a manifest, or a fixed number as it is.

    Args:
        value (str | Decimal | Mapping[str, str | Decimal]): A number, or a mapping
            with `min` and `max`.

    Returns:
        Decimal: The lower bound.

    Examples:
        >>> lower_bound({"min": "2.4000", "max": "2.6000"})
        Decimal('2.4000')
    """
    return Decimal(value["min"] if isinstance(value, Mapping) else value)


def middle_of(value: Written) -> Decimal:
    """Give the middle of a range of a manifest, or a fixed number as it is.

    Args:
        value (str | Decimal | Mapping[str, str | Decimal]): A number, or a mapping
            with `min` and `max`.

    Returns:
        Decimal: `(min + max) / 2` for a range.

    Examples:
        >>> middle_of({"min": "4.000", "max": "6.000"})
        Decimal('5.000')
    """
    if isinstance(value, Mapping):
        return (Decimal(value["min"]) + Decimal(value["max"])) / 2
    return Decimal(value)


def build_lowest_costs(manifest: Mapping[str, Any]) -> dict[str, Decimal]:
    """Build what one unit of every item costs at best.

    A material costs the lowest lower bound of its price over the catalogues that
    sell it; a made item the lowest costs of the inputs of its recipe `standard`,
    every quantity 1, plus the lowest cost of its line item over the lines that make
    it. Yield is 1 and storage, interest and losses cost nothing.

    Args:
        manifest (Mapping[str, Any]): A generated manifest as JSON.

    Returns:
        dict[str, Decimal]: The lowest cost of every item.

    Raises:
        InputError: If a material is in no catalogue.

    Examples:
        >>> from factory_simulator.engine.generation import generate_manifest
        >>> counts = {
        ...     "materials": 1,
        ...     "components": 1,
        ...     "products": 1,
        ...     "suppliers": 1,
        ...     "customers": 1,
        ...     "lines": 1,
        ... }
        >>> sorted(build_lowest_costs(generate_manifest(counts, 0)))
        ['component-1', 'material-1', 'product-1']
    """
    costs: dict[str, Decimal] = {}
    for material in manifest["materials"]:
        prices = [
            lower_bound(supplier["catalogue"][material]["price"])
            for supplier in manifest["suppliers"].values()
            if material in supplier["catalogue"]
        ]
        if not prices:
            raise InputError(f"materials.{material}: is in no catalogue")
        costs[material] = min(prices)
    line_costs: dict[str, Decimal] = {}
    for line in manifest["lines"].values():
        for item, terms in line["items"].items():
            cost = Decimal(terms["cost"])
            line_costs[item] = min(cost, line_costs.get(item, cost))
    for kind in ("components", "products"):
        for item, body in manifest[kind].items():
            inputs = body["recipes"]["standard"]
            costs[item] = sum(
                (costs[input_id] for input_id in inputs), line_costs[item]
            )
    return costs


@in_decimal_context
def build_economic_profile(manifest: Mapping[str, Any]) -> EconomicProfile:
    """Build the economic profile of a generated manifest from its text alone.

    Args:
        manifest (Mapping[str, Any]): A generated manifest as JSON.

    Returns:
        EconomicProfile: The lowest cost, best margin, service value and middle demand
            of every customer product, the useful demand coverage, the margin share
            and the class.

    Raises:
        InputError: If a material is in no catalogue.

    Examples:
        >>> from factory_simulator.engine.generation import generate_manifest
        >>> counts = {
        ...     "materials": 1,
        ...     "components": 1,
        ...     "products": 1,
        ...     "suppliers": 1,
        ...     "customers": 1,
        ...     "lines": 1,
        ... }
        >>> build_economic_profile(generate_manifest(counts, 0)).economic_class
        'profitable'
    """
    costs = build_lowest_costs(manifest)
    profiles: list[CustomerProductProfile] = []
    sales = Decimal(0)
    for customer, body in manifest["customers"].items():
        for product, terms in body["products"].items():
            price = Decimal(terms["price"])
            income = price - Decimal(terms["transport_cost"])
            avoided = Decimal(terms["lost_sale_penalty"]) + terms["patience"] * Decimal(
                terms["late_penalty"]
            )
            profiles.append(
                CustomerProductProfile(
                    customer=customer,
                    product=product,
                    lowest_cost=costs[product],
                    best_margin=income - costs[product],
                    service_value=income + avoided,
                    demand=middle_of(terms["demand"]),
                )
            )
            sales += price * profiles[-1].demand
    demand = sum((profile.demand for profile in profiles), Decimal(0))
    useful = sum(
        (
            profile.demand
            for profile in profiles
            if profile.service_value > profile.lowest_cost
        ),
        Decimal(0),
    )
    margins = sum(
        (profile.best_margin * profile.demand for profile in profiles), Decimal(0)
    )
    if any(profile.best_margin > 0 for profile in profiles):
        economic_class = "profitable"
    elif any(profile.service_value > profile.lowest_cost for profile in profiles):
        economic_class = "penalty-driven"
    else:
        economic_class = "unproductive"
    coverage = round_to(useful / demand, 4) if demand != 0 else Decimal("0.0000")
    margin_share = round_to(margins / sales, 4) if sales != 0 else Decimal("0.0000")
    return EconomicProfile(
        customer_products=tuple(profiles),
        useful_demand_coverage=coverage,
        margin_share=margin_share,
        economic_class=economic_class,
    )
