# Coordinated planning

This example asks a planner role and a procurement role of a hosted model for their
decisions. A reviewer role receives their proposals and check results and returns the
final plan. Memory holds the last two closed periods. When the check rejects the plan,
the reviewer repairs it up to two times, then the rejected decisions are removed. The
command replays the saved model replies offline or makes real requests to
`gpt-6.1-terra` live.

## Requirements

The offline mode needs `Factory-Simulator-Reproduction.zip`. Follow the
[reproduction guide](../../scripts/reproduction/README.md) for the matching code,
data download and installation. Place the ZIP beside the repository and run commands
from the repository root. Offline mode reads no credential and opens no network
connection.

The live mode reads `OPENAI_API_KEY` from the environment. Export it in your shell and
check the current prices of the model before the command.

Neither mode needs a running server. The command starts the HTTP interface in its own
process, with its database in the output directory.

## Smallest example

```sh
uv run python -m examples.coordinated_planning.run --offline \
  --archive ../Factory-Simulator-Reproduction.zip \
  --output data/examples/coordinated-planning/offline
```

The command has a mode selector: `--offline` gives the agent the saved replies of the
archive, `--live` sends real requests. Offline, it prints `A3: exact` when every
request, decision, period, result and world equals the archive.

## Inputs and outputs

The command accepts `--offline` or `--live`, `--case` (default `A3`), `--output` (a new
directory, required) and `--archive` (offline only). Live, it also requires
`--budget-usd` (at most 50), `--input-usd-per-million` and `--output-usd-per-million`.
Case A3 plays the small fixture over 3 periods, B3 `steady-market` over 52 periods, and
C1 and C2 `notice` over 52 periods, all with seed 7; `all` plays the four in order. The
offline mode plays all four in about 9 minutes.

Every request asks for at most 8192 output tokens with reasoning effort `low`. The
`coordinated` strategy asks the planner, procurement and reviewer roles in order, with up
to two repair calls per period. Before each attempt the budget reserves the cost of the
whole input and of 8192 output tokens, and a reply settles it at its usage. A call has
at most two attempts within 600 seconds; a partial reply is never sent again.

The output holds `summary.json`, `runs.duckdb` and one folder per case. A case folder
holds `start.json`, `settings.json`, `decisions.json`, `periods.json`, `result.json`,
`world.json`, `audit.json`, `status.json` and `model-calls.jsonl`, with the export ZIP of
the run under `export/RUN_ID/`. Offline, each case folder also holds
`controller-verification.json`. Live, the output holds `budget.json` and
`transport-events.jsonl`; the spending is an estimate, not the provider invoice.

## Errors

An existing output directory, a missing mode or archive, a missing budget or price, or a
missing `OPENAI_API_KEY` stops the command before it writes anything. An archive whose
files differ from its `SHA256SUMS.json` is refused after extraction. Offline, a request
or a played file that differs from the archive stops the command. Live, a failure blocks
the budget and stops the command; `status.json` keeps the failure and
`pending-decisions.json` the decisions of the period in progress. Inspect the record
before starting another run.
