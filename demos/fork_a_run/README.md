# Fork a run

This demo finishes a three-period run, then forks it at the start of period 2 and
finishes the new run in the same world.

## Requirements

Run the command from the repository root. Install the base project and start the HTTP
server. No provider package or credential is required.

## Smallest example

```sh
uv run python -m demos.fork_a_run.run --seed 7
```

The parent run submits no decisions. The API fork repeats its closed period 1 and
starts at period 2. The demo submits no decisions for the remaining periods.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7) and `--output` (default `data/demos/fork-a-run/`). The fork period is 2.
It writes `summary.json` and the export ZIP `RUN_ID.zip` of both runs, each under
`data/demos/fork-a-run/RUN_ID/`.

The fork summary names the parent run and the fork period. A fork is a separate run
with the same scenario and seed, and the parent stays as it is.

## Errors

An unreachable server, a refused request, a fork from an unfinished run or an existing
output directory stops the command with the related route or path.
