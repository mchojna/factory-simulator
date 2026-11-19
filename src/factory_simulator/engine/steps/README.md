# Engine steps

The steps: each gives a new state from the state before it.

## Contents

- [__init__.py](__init__.py): The steps: each gives a new state from the state before it.
- [close.py](close.py): The close of a period: production, wear, storage, penalties, interest and measures.
- [deliveries.py](deliveries.py): The arrivals of a period: deliveries, backfills and transfers.
- [events.py](events.py): The events of a period: payments, disruptions, breakdowns and new orders.
- [execution.py](execution.py): The execution of decisions: by kind, ship, cancel, transfer, repair, produce, buy.
- [observation.py](observation.py): The observation: what the agent sees in a period.
- [period.py](period.py): The period: the state before period 1, its start and end, and its outcomes.

## Entry point

Start with [__init__.py](__init__.py).
