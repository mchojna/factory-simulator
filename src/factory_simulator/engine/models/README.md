# Engine models

The frozen dataclasses: inputs, world, state and decisions, one module per object.

## Contents

- [__init__.py](__init__.py): The frozen dataclasses: inputs, world, state and decisions, one module per object.
- [decisions.py](decisions.py): The decisions: ship, produce, buy, repair, cancel, transfer and a submission.
- [manifest.py](manifest.py): The factory a manifest describes: its items, partners, lines, warehouses and cash.
- [scenario.py](scenario.py): A scenario: horizon, start, demand shapes, forecasts, disruptions and cascades.
- [state.py](state.py): The state of a run: orders, ledger rows, events, outcomes and the observation.
- [trace.py](trace.py): The transition trace: exact inputs, outcomes and snapshots of an operation.
- [world.py](world.py): The world of a run: every value drawn from the seed, and the description.

## Entry point

Start with [__init__.py](__init__.py).
