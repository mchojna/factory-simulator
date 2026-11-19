# Resume a run

This example stores a run after period 1 and resumes that same run in a second command.
The simulator database keeps the closed period and the unfinished run across server
restarts.

## Requirements

Run both commands from the repository root. Install the base project and start the
HTTP server. Keep the same database for both commands. No provider credential is
required.

## Smallest example

```sh
uv run python -m examples.resume_a_run.run --seed 7
uv run python -m examples.resume_a_run.run --run-id RUN_ID
```

The first command prints a checkpoint path. Copy the `run_id` from that JSON file into
the second command. The second command reads the run and its current observation over
HTTP, then submits empty decisions until period 3 ends.

## Inputs and outputs

The first command accepts `--server` (default `http://127.0.0.1:8000/api/v1`),
`--seed` (default 7) and `--output` (default `data/examples/resume-a-run/`); the second
accepts `--server`, `--run-id` and `--output`. The first writes `checkpoint.json` under
`data/examples/resume-a-run/RUN_ID/`. The second writes `summary.json` and the export ZIP
`RUN_ID.zip` in the same folder after it finishes the run.

## Errors

Use the same server and database for both commands. An unknown or finished run, a
refused HTTP request or a conflicting output directory stops the command with its
identifier or route.
