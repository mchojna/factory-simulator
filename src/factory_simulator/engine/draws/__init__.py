"""The draws: the world of a run drawn from its seed, one module per kind of value.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
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
    >>> scenario = Scenario(horizon=2)
    >>> draw_world(factory, scenario, 0) == draw_world(factory, scenario, 0)
    True
"""
