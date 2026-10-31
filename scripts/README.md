# Scripts

The Bash commands that set up and check the environment, run the server, build the
documentation and export the transport record.

## Contents

- [build_docs.sh](build_docs.sh): builds the documentation site.
- [check_server.sh](check_server.sh): starts a temporary server and reads the
  manifests.
- [exclude_readme.py](exclude_readme.py): the MkDocs hook that removes the collection
  README.
- [export_transport.sh](export_transport.sh): exports the transport record of a stopped
  server.
- [serve_docs.sh](serve_docs.sh): serves one documentation collection.
- [setup_environment.sh](setup_environment.sh): installs the locked environment.
- [start_server.sh](start_server.sh): starts the HTTP server.
- [verify_environment.sh](verify_environment.sh): checks the lock and the base imports.

## Entry point

Start with [setup_environment.sh](setup_environment.sh).

## Requirements

Install `uv` before running a script. Use Bash 3.2 or later on macOS or Linux. `uv`
reads the required Python version and installs Python 3.14 when it is not available.
Setup and verification make no model-provider request and need no credentials.

A script with fixed arguments prints a `Usage:` line and exits with 2 when they are
wrong. A failure exits with 1. Each error message starts with the name of its script.

## Setup

Set `REPOSITORY` to the checkout path. Each script finds the repository from its own
location, so the current working directory can be anywhere:

```sh
REPOSITORY=/path/to/factory-simulator
bash "$REPOSITORY/scripts/setup_environment.sh"
bash "$REPOSITORY/scripts/setup_environment.sh" --development --docs
bash "$REPOSITORY/scripts/setup_environment.sh" --provider anthropic --provider openai
```

The first command installs the simulator and its base dependencies with `uv.lock`. The
second also installs the development and documentation tools. The third installs the
chosen provider groups: `anthropic`, `google`, `openai` and `openrouter`. The `openai`
group installs the tokenizer that counts OpenAI input tokens. A provider group sends no
request. Setup refuses an unknown option or provider and uses `--locked`, so it keeps
`uv.lock` as it is.

`uv` is a required preinstalled tool. Setup installs Python 3.14, the simulator and the
selected dependency groups. The base application and the mathematical optimizers need
no provider group.

## Environment check

```sh
bash "$REPOSITORY/scripts/verify_environment.sh"
```

The check compares the lock with `pyproject.toml` and imports the base application, the
HTTP client and the no-decisions optimizer. It synchronizes no package and reads no
provider credential. It reports a stale lock. A missing base package fails the import
check; run setup before the check.

## Server

```sh
bash "$REPOSITORY/scripts/start_server.sh"
```

Run setup first. The server listens on `127.0.0.1:8000` and writes to
`data/records/runs.duckdb`. Set `FACTORY_SIMULATOR_DATABASE_URL` to choose another
database URL. The script keeps a URL that is already set and passes extra arguments to
Uvicorn. Stop the server with Ctrl-C.

## Smoke check

```sh
bash "$REPOSITORY/scripts/check_server.sh"
```

The check picks a free local port, starts its own server with a temporary database
under `data/records/`, and reads the list of example manifests over HTTP. It stops only
the process it started and removes only its temporary directory. It starts no run and no
model call. A timeout or a response other than 200 fails the command, which then prints
the server log before it removes the temporary files.

## Documentation

The development documentation and the hub use separate MkDocs configurations:

```sh
bash "$REPOSITORY/scripts/serve_docs.sh" development
bash "$REPOSITORY/scripts/build_docs.sh" "$REPOSITORY/site/public"
```

The serve command takes `development` and uses port 8001. The build command runs a
strict build of the development documentation and the documentation hub, each in its
own temporary directory. It assembles one site with the development pages at the root
and the hub under `/documentation/`. The output directory must be new or empty. The hook in `exclude_readme.py` removes the
collection README before the language folders are resolved, so the English and Polish
READMEs are the landing pages.

## Transport export

Stop the server before exporting its DuckDB database. Use a new destination path:

```sh
bash "$REPOSITORY/scripts/export_transport.sh" \
  data/records/runs.duckdb \
  data/records/transport.zip
```

The command checks the raw request and response bodies, including the bodies of earlier
export responses. The transport ZIP holds the request and response bodies that the
run archives leave out.

## Outputs

| Script | Output |
| --- | --- |
| `setup_environment.sh` | The local virtual environment. |
| `verify_environment.sh` | No file. |
| `start_server.sh` | The database at the chosen URL, `data/records/runs.duckdb` by default. |
| `check_server.sh` | No file; it removes its temporary database and log. |
| `serve_docs.sh` | No file. |
| `build_docs.sh` | The assembled site in the chosen output directory. |
| `export_transport.sh` | The transport ZIP at the chosen path. |

No command changes the committed lock.
