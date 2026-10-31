"""The decisions: the checks and execution of each decision on the plant.

Examples:
    >>> import pkgutil, factory_simulator.engine.decisions as decisions
    >>> sorted(module.name for module in pkgutil.iter_modules(decisions.__path__))
    ['buy', 'cancel', 'plant', 'produce', 'repair', 'ship', 'transfer']
"""
