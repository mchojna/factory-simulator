# Tool-guided planning

This example lets a hosted model read public fields and check candidate decisions before
it returns its plan. The model keeps the cash, stock and decision outcomes of the last
two closed periods. The command makes real requests to the selected model over three
factory periods.

## Requirements

Start the HTTP service with `bash scripts/start_server.sh`. Copy the environment
template from the repository root and fill the selected provider key and model:

```sh
cp .env.template .env
```

The template contains `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` and `OPENAI_API_KEY`.
Fill only the provider you use, set `MODEL_PROVIDER` and `MODEL_NAME`, then export the
file in your shell:

```sh
set -a
source .env
set +a
```

`.env` is ignored by Git. Example commands use exported variables and leave `.env`
unread.

## Smallest example

```sh
uv run python -m examples.tool_guided_planning.run
```

The command has no mode selector and no prepared responses. `--provider` and `--model`
select the provider and the model. Each falls back to `MODEL_PROVIDER` or `MODEL_NAME`,
and the command stops when one of them has no value. Missing credentials, invalid model
output or infeasible decisions stop the command.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7), `--output` (default `data/examples/tool-guided-planning/`), `--provider`
(default `MODEL_PROVIDER`), `--model` (default `MODEL_NAME`), `--max-input-words`
(default 16384), `--max-output-tokens` (default 4096), `--timeout-seconds` (default 120)
and `--retries` (default 0). The `tools_memory` strategy has at most four turns per
period, the final answer included.

The command also runs the myopic optimizer and the no-decisions agent on the same
manifest, scenario and seed. It writes `example-summary.json` and `model-calls.jsonl`
under `data/examples/tool-guided-planning/tool-guided-planning-ID/`, where `ID` is 12
random hexadecimal digits. In that folder, `tools_memory/RUN_ID/`, `myopic/RUN_ID/` and
`no_decisions/RUN_ID/` each hold the `summary.json` and the export ZIP `RUN_ID.zip` of
one run. The call record keeps the provider requests, responses, errors, checks and
closed periods. A failure leaves the call record in place. The summary records no
monetary spending.

## Errors

A missing provider key fails before the command creates simulator runs. Input word
limits, output token limits and call limits stop the model. A reply that is not complete
stops the model, and the call record keeps it. After a rate limit, a timeout, a
transport failure or a provider service failure the command sends the request again, up
to `--retries` times; every other provider failure stops the command at once. Invalid
output is reported as it is, with no empty or prepared plan in its place. Correct the
configuration or inspect the saved response before starting another run.
