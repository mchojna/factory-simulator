# Demo utilities

The HTTP client inputs, the command line, the model demos and the hosted providers of
the demos.

## Contents

- [__init__.py](__init__.py): the default server address.
- [client.py](client.py): the small fixtures and the HTTP run setup.
- [cli.py](cli.py): the common arguments and the saved finished runs.
- [model.py](model.py): the live model strategies and the saved-result comparisons.
- [providers.py](providers.py): the Anthropic, Google, OpenAI and OpenRouter adapters.
- [fixtures/](fixtures/README.md): the small factory and scenario.

## Entry point

Start with [model.py](model.py) for language-model planning or [cli.py](cli.py) for
the optimizer and run-management demos.
