# API core

The core of the HTTP interface: settings, errors, JSON, numbers, one module per part.

## Contents

- [__init__.py](__init__.py): The core of the HTTP interface: settings, errors, JSON, numbers, one module per part.
- [config.py](config.py): The settings of the server: the variables FACTORY_SIMULATOR_* and their defaults.
- [errors.py](errors.py): The errors of a request: not found, answered 404, and conflict, answered 409.
- [json.py](json.py): The one writer of JSON: responses and canonical JSON with exact decimals.
- [numbers.py](numbers.py): The numbers of the HTTP interface: their types, the reader of JSON and validation.

## Entry point

Start with [__init__.py](__init__.py).
