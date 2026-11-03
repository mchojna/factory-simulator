# Examples

Commands that operate the factory through its HTTP interface, with the benchmark
optimizers or real hosted language models.

## Setup

Install with `bash scripts/setup_environment.sh`. Start the HTTP service with
`bash scripts/start_server.sh`. Commands run from the repository root and use
`http://127.0.0.1:8000/api/v1` by default. Generated records go under `data/examples/`.

## Simulator examples

- [Run without decisions](run_without_decisions/README.md): play a run with empty
  decisions.
- [Plan production](plan_production/README.md): plan with the myopic optimizer.
- [Check decisions](check_decisions/README.md): check a candidate shipment.
- [Resume a run](resume_a_run/README.md): continue a stored run.
- [Fork a run](fork_a_run/README.md): create an alternative continuation.
- [Inspect a record](inspect_a_record/README.md): inspect the export ZIP of a finished
  run.

## Language-model examples

- [Single-prompt planning](single_prompt_planning/README.md): plan from the public
  state.
- [Tool-guided planning](tool_guided_planning/README.md): inspect public facts and
  check plans.
- [Coordinated planning](coordinated_planning/README.md): combine planner, procurement
  and reviewer roles.
- [Compare optimizers](compare_optimizers/README.md): compare saved example results
  offline.

Copy the [environment template](../.env.template) to `.env`, set the selected provider
key, `MODEL_PROVIDER` and `MODEL_NAME`, then export them in your shell:

```sh
cp .env.template .env
# Edit .env before loading it.
set -a
source .env
set +a
uv run python -m examples.single_prompt_planning.run
```

The model commands always send real provider requests. They have no mode selector
and no prepared responses. `.env` is ignored by Git and is not loaded automatically.
`--provider` and `--model` override `MODEL_PROVIDER` and `MODEL_NAME`. The providers
are `anthropic`, `google` and `openai`, and all of them use the base dependencies. The
Inputs and outputs section of each command names its limits.

Every model example completes its run with these models, checked on 2026-11-03:

| Provider | Model |
| --- | --- |
| `anthropic` | `claude-sonnet-5-5` |
| `google` | `gemini-4-argon` |
| `openai` | `gpt-6.1-terra` |

Input limits count whitespace-separated words in message content. The JSON in a message
has a space after every comma and colon, so every key and value is a word. Output limits
count tokens.

Every reply in `model-calls.jsonl` keeps the stop reason of the provider and its
completion: `complete`, `truncated`, `refused` or `other`. Only a complete reply goes on
to the decision check. The JSON array or object at the end of a reply is read, also
inside a Markdown code block, and the call record keeps the reply as it is. The token
counts have one meaning for every provider: `input_tokens` holds every input token with
cached tokens, `output_tokens` every generated token with reasoning tokens, and
`cached_input_tokens` and `reasoning_tokens` hold those parts. A count the provider does
not report is `null`.
Every provider failure has a kind: `authentication`, `invalid_request`, `rate_limit`,
`timeout`, `transport`, `service` or `invalid_response`.

Each model example also runs the myopic optimizer and the no-decisions agent on the same
small factory, scenario and seed. The saved requests, responses and export ZIPs of
the runs support inspection.
