"""The writers: the dataclasses of the engine as JSON, one module per body.

Examples:
    >>> from factory_simulator import engine
    >>> from factory_simulator.api.services.writers.values import plain
    >>> plain(engine.Range(min=1, max=3))
    {'min': 1, 'max': 3, 'distribution': 'uniform'}
"""
