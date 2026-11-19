"""The checks: rules that join several keys or objects.

Examples:
    >>> from factory_simulator.engine.checks.scenario import check_listed_target
    >>> check_listed_target(("mill", "mill"), {"mill": "a supplier"}, "target")
    Traceback (most recent call last):
    ...
    factory_simulator.engine.numbers.InputError: target.1: repeats mill
"""
