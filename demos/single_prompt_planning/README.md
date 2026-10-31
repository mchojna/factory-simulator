# Single-prompt planning

This demo asks a hosted model for the decisions of each period from the public factory
description and the current observation. The command makes real requests to the selected
model over three factory periods.

## Requirements

Start the HTTP service with `bash scripts/start_server.sh`. Copy the environment
template from the repository root and fill the selected provider key and model:

```sh
cp .env.template .env
```

The template contains `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY` and
`OPENROUTER_API_KEY`. Fill only the provider you use, set `MODEL_PROVIDER` and
`MODEL_NAME`, then export the file in your shell:

```sh
set -a
source .env
set +a
```

`.env` is ignored by Git. Demo commands use exported variables and leave `.env` unread.
OpenAI token counting also requires `bash scripts/setup_environment.sh --provider
openai`.

## Smallest example

```sh
uv run python -m demos.single_prompt_planning.run \
  --provider "$MODEL_PROVIDER" --model "$MODEL_NAME"
```

The command has no mode selector and no prepared responses. `--model` is required.
Missing credentials, invalid model output or infeasible decisions stop the command.
Provider transport errors use only the explicitly selected retry count.

## Inputs and outputs

The command accepts `--server` (default `http://127.0.0.1:8000/api/v1`), `--seed`
(default 7), `--output` (default `data/demos/single-prompt-planning/`), `--provider`
(default `openai`), `--model` (required), `--max-input-tokens` (default 16384),
`--max-output-tokens` (default 1024), `--timeout-seconds` (default 30) and `--retries`
(default 0). The `single_prompt` strategy makes one model call per period.

The command also runs the myopic optimizer and the no-decisions agent on the same
manifest, scenario and seed. It writes `demo-summary.json` and `model-calls.jsonl` under
`data/demos/single-prompt-planning/single-prompt-planning-ID/`, where `ID` is 12 random
hexadecimal digits. In that folder, `single_prompt/RUN_ID/`, `myopic/RUN_ID/` and
`no_decisions/RUN_ID/` each hold the `summary.json` and the export ZIP `RUN_ID.zip` of
one run. The call record keeps the provider requests, responses, errors, checks and
closed periods. A failure leaves the call record in place. The summary records no
monetary spending.

## Errors

A missing provider key fails before the command creates simulator runs. A token or call
limit stops the model. Invalid output is reported as it is, with no empty or prepared
plan in its place. Correct the configuration or inspect the saved response before
starting another run.
