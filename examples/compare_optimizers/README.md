# Compare optimizers

This example compares the finished runs of one model example from its saved summary. It
makes no provider request and plays no run.

## Requirements

Run a language-model example first. No provider credential is required.

## Smallest example

Pass the summary path that the language-model example printed:

```sh
uv run python -m examples.compare_optimizers.run \
  --summary path/to/example-summary.json
```

## Inputs and outputs

The command accepts `--summary` (required), one saved summary of a model example, and
`--output` (default `data/examples/compare-optimizers/`), the folder of
`comparison.json`. The report keeps the seed, the method names, the profits and the
paths of the run summaries. The model, the myopic optimizer and the no-decisions agent
play the same scenario. Their export ZIPs and `model-calls.jsonl` hold the evidence.

## Errors

A missing summary or invalid JSON stops the command.
