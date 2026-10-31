# Run without decisions

This demo creates a three-period run and submits an empty decision list in every
period.

## Requirements

Run the command from the repository root. Install the base project and start the HTTP
server. No provider package or credential is required.

## Smallest example

```sh
uv run python -m demos.run_without_decisions.run --seed 7
```

The command creates the small demo factory and scenario through HTTP, then starts a
run with seed 7. It prints the path to `summary.json` after the run finishes.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7) and `--output` (default `data/demos/run-without-decisions/`). The horizon
is three periods. It writes `summary.json` and the export ZIP `RUN_ID.zip` under
`data/demos/run-without-decisions/RUN_ID/`.

## Errors

An unreachable server, a refused HTTP request or an existing output directory makes
the command fail with the affected address, route or file path.
