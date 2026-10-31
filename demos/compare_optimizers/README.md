# Compare optimizers

This demo compares the finished runs of one model demo from its saved summary. It
makes no provider request and plays no run.

## Requirements

Run a language-model demo first. No provider package or credential is required.

## Smallest example

Pass the summary path that the language-model demo printed:

```sh
uv run python -m demos.compare_optimizers.run \
  --summary path/to/demo-summary.json
```

## Inputs and outputs

The command accepts `--summary` (required), one saved summary of a model demo, and
`--output` (default `data/demos/compare-optimizers/`), the folder of
`comparison.json`. The report keeps the seed, the method names, the profits and the
paths of the run summaries. The model, the myopic optimizer and the no-decisions agent
play the same scenario. Their export ZIPs and `model-calls.jsonl` hold the evidence.

## Errors

A missing summary or invalid JSON stops the command.
