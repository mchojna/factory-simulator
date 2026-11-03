# API services runs

The service of runs: one module per task, from starting a run to exporting it.

## Contents

- [__init__.py](__init__.py): The service of runs: one module per task, from starting a run to exporting it.
- [export.py](export.py): The export of a finished run: a ZIP of its tables, its operations and its inputs.
- [fork.py](fork.py): The fork of a run: a new run from a period of a finished run, its past replayed.
- [memory.py](memory.py): The memory of the server: the running runs it keeps and their locks.
- [periods.py](periods.py): The closed periods of a run: each with its six steps and its ledger rows.
- [replay.py](replay.py): The replay of a run: its periods played again from the record, to rebuild or fork it.
- [results.py](results.py): The result of a finished run: profit, its terms and the measures of the run.
- [rows.py](rows.py): The rows of a closed period: period, events, outcomes, ledger, measures and traces.
- [runs.py](runs.py): The life of a run: start it, read it, submit to it and check it.
- [stored.py](stored.py): A stored run: its identifier, the run read from the record and its inputs.

## Entry point

Start with [__init__.py](__init__.py).
