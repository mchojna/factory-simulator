# Benchmark program

The profit program: its inputs, its solve and its decisions, one module per task.

## Contents

- [__init__.py](__init__.py): The profit program: its inputs, its solve and its decisions, one module per task.
- [decisions.py](decisions.py): The decisions of a solution: rounded down, ordered, checked and fitted.
- [expected_source.py](expected_source.py): The planning input of a limited optimizer: expected values in place of the world.
- [solve.py](solve.py): The profit program: a linear or mixed-integer program of a window, solved with HiGHS.
- [world_source.py](world_source.py): The world as a planning input: the coefficients of the program read from a world.

## Entry point

Start with [__init__.py](__init__.py).
