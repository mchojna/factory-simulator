# Plan production

This example uses the myopic optimizer to plan and submit decisions for a three-period
factory.

## Requirements

Run the command from the repository root. Install the base project and start the HTTP
server. No provider credential is required.

## Smallest example

```sh
uv run python -m examples.plan_production.run --seed 7
```

The command creates its factory and scenario through HTTP. The optimizer gets the same
description and period observations as any agent. It checks each plan through the
HTTP interface and records its proposals, checks, fitted decisions and solve reports.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7) and `--output` (default `data/examples/plan-production/`). The horizon is
three periods. It writes `summary.json` and the export ZIP `RUN_ID.zip` under
`data/examples/plan-production/RUN_ID/`.

The summary names `myopic` as the optimizer. It contains the solver report of every
solve, each with a limit of 2 seconds. The myopic optimizer plans one period at a time.

## Errors

An unreachable server, a refused HTTP request, a solver failure or an existing output
directory stops the command with the error it met.
