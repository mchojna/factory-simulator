# Engine rules

The rules steps, decisions and measures share: read-only, one module per subject.

## Contents

- [__init__.py](__init__.py): The rules steps, decisions and measures share: read-only, one module per subject.
- [demand.py](demand.py): The demand shapes of a scenario: the factor of demand of a customer product.
- [disruptions.py](disruptions.py): The rules of a disruption: when it acts, what it acts on, and its effect.
- [items.py](items.py): The rules of items and warehouses: kinds, paths, space, inputs and where items go.
- [lines.py](lines.py): The hours of a line: the hours available, repair hours available and overtime hours.
- [parameters.py](parameters.py): The parameters of a factory: paths, those drawn per period or hidden, and bounds.
- [space.py](space.py): The space in a warehouse: what stock, production, supplier orders and transfers take.
- [suppliers.py](suppliers.py): The terms of supplier orders: the lead time, the delivery outcome and the price.
- [targets.py](targets.py): The targets of disruptions, demand shapes and forecasts: what each names.

## Entry point

Start with [__init__.py](__init__.py).
