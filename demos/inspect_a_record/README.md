# Inspect a record

This demo reads identifiers and table names from the export ZIP of a finished run. It
uses no server and never opens a simulator database.

## Requirements

Run the command from the repository root. Use the export ZIP of a finished simulator
run and install the base project. No provider package or credential is required.

## Smallest example

```sh
uv run python -m demos.inspect_a_record.run \
  --archive data/demos/run-without-decisions/RUN_ID/RUN_ID.zip
```

The command checks the ZIP members, reads `run.json`, `manifest.json` and
`scenario.json`, and writes an inspection summary. It makes no HTTP request.

## Inputs and outputs

The command accepts `--archive` (required) and `--output` (default
`data/demos/inspect-a-record/`). It writes `inspection.json` under
`data/demos/inspect-a-record/RUN_ID/`. The summary contains the run and scenario
identifiers, the seed, the manifest and scenario names, the member names and the
SHA-256 of the export ZIP.

## Errors

An unreadable or damaged ZIP, a missing required member or an existing output folder
stops the command with the path of the export ZIP or the member name.
