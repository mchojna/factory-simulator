# Benchmark optimizers

The optimizers: the agents of the benchmark, one module per agent.

## Contents

- [__init__.py](__init__.py): The optimizers: the agents of the benchmark, one module per agent.
- [aligned.py](aligned.py): The aligned optimizer: the profit program over a window of known orders.
- [buffered_rolling.py](buffered_rolling.py): The buffered rolling optimizer: the rolling optimizer that keeps a buffer of stock.
- [full_horizon.py](full_horizon.py): The full-horizon optimizer: the program to the horizon, from what an agent knows.
- [informed.py](informed.py): The informed optimizer: the rolling optimizer that knows the ranges a twin shows.
- [myopic.py](myopic.py): The myopic optimizer: the profit program over the current period only.
- [no_decisions.py](no_decisions.py): The agent of no decisions: an agent that decides nothing in any period.
- [reference.py](reference.py): The reference optimizer: the profit program with the whole world of a run.
- [rolling.py](rolling.py): The rolling optimizer: the profit program over a window, from what an agent knows.

## Entry point

Start with [__init__.py](__init__.py).
