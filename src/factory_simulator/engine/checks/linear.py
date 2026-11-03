"""The check of linearity: no minimum quantity, discount or changeover in a factory.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine.models.manifest import Cash
    >>> cash = Cash(
    ...     credit_limit=Decimal(0),
    ...     credit_interest=Decimal(0),
    ...     debit_interest=Decimal(0),
    ...     overdraft_interest=Decimal(0),
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
    >>> is_linear(factory)
    True
"""

from factory_simulator.engine.models.manifest import Factory
from factory_simulator.engine.numbers import in_decimal_context


@in_decimal_context
def is_linear(factory: Factory) -> bool:
    """Tell whether a factory is linear.

    Args:
        factory (Factory): The factory.

    Returns:
        bool: True when no catalogue entry has a minimum quantity or discounts and no
            line item has a changeover time or cost.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Supplier,
        ... )
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ...     min_quantity=Decimal(20),
        ... )
        >>> factory = Factory(
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> is_linear(factory)
        False
    """
    buys_linear = all(
        entry.min_quantity is None and not entry.discounts
        for supplier in factory.suppliers.values()
        for entry in supplier.catalogue.values()
    )
    produces_linear = all(
        terms.changeover_time is None and terms.changeover_cost is None
        for line in factory.lines.values()
        for terms in line.items.values()
    )
    return buys_linear and produces_linear
