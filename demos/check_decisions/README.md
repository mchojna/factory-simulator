# Check decisions

This demo asks the HTTP interface to check one shipment before it submits that
shipment. The check records an interaction and leaves the run unchanged.

## Requirements

Run the command from the repository root. Install the base project and start the HTTP
server. No provider package or credential is required.

## Smallest example

```sh
uv run python -m demos.check_decisions.run --seed 7
```

The small scenario starts with four monitors and demand for four monitors in period 1.
The demo builds a shipment from the observed order, checks it, submits it and completes
the remaining periods with empty decisions.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7) and `--output` (default `data/demos/check-decisions/`). The horizon is
three periods. It writes `summary.json`, with the check outcomes, and the export ZIP
`RUN_ID.zip` under `data/demos/check-decisions/RUN_ID/`.

## Errors

An unreachable server, a refused check or submission, or an existing output directory
stops the command. Check the reported API route and decision outcome.
