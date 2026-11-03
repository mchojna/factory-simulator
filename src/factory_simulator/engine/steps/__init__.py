"""The steps: each gives a new state from the state before it.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine.steps.observation import forecasts_seen
    >>> forecasts_seen((Decimal("4.000"), None), 9)
    (ForecastSeen(period=10, quantity=Decimal('4.000')),)
"""
