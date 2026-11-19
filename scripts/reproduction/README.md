# Reproduction

The Python commands that extract the evidence archive, audit its recorded inputs and
replay its saved decisions. None of them needs a model credential.

## Contents

- [article/](article/README.md): the controlled article examples and Figures 1-6
  from the archived data.
- [prepare_reproduction.py](prepare_reproduction.py): extracts the archive and checks
  every file against its manifest.
- [check_recorded_inputs.py](check_recorded_inputs.py): checks the saved requests
  against the saved runs and prints a JSON report.
- [replay_saved_actions.py](replay_saved_actions.py): plays the saved decisions of one
  run or all eight again and compares their periods, results and worlds.

## Entry point

Start with [prepare_reproduction.py](prepare_reproduction.py).

## Usage

Use the code and data for the same reproduction revision. The code is tag `v1.0.0`
of the [version 1.0.0 release](https://github.com/mchojna/factory-simulator/releases/tag/v1.0.0).
The data is `Factory-Simulator-Reproduction.zip` of the
[reproduction release](https://github.com/mchojna/factory-simulator/releases/tag/factory-simulator-reproduction),
with SHA-256 `3340137bc74bb754ded7b350db4fcf6c0b5e7b782b2113d5fb09abadb5d67d8f`.
Do not substitute an older release ZIP, which includes a second source tree.
Preserve that revision when reproducing the article.

Place the downloaded ZIP **beside** the checkout, not inside it:

```text
work/
  Factory-Simulator-Reproduction.zip
  factory-simulator/
```

Run every command below from `work/factory-simulator/`. Install Python 3.14.10
with a compatible uv (`>=0.12.10,<0.14`) and run `uv sync --locked` first. The default
development group supplies the plotting and test dependencies.

```sh
uv run python -m scripts.reproduction.prepare_reproduction \
  --archive ../Factory-Simulator-Reproduction.zip --output data/reproduction
PACKAGE=data/reproduction/Factory-Simulator-Reproduction
uv run python -m scripts.reproduction.check_recorded_inputs --package-root "$PACKAGE"
uv run python -m scripts.reproduction.replay_saved_actions --case all \
  --package-root "$PACKAGE" --output data/replay-check
```

The extraction refuses a member outside the package folder, an existing output
directory and a file that differs from the `SHA256SUMS.json` of the package. The audit
reads only JSON files, prints its report and exits with 1 when a check fails. The replay
takes one of the cases `A3`, `B3`, `C1`, `C2`, `B-rolling`, `B-reference`, `C1-rolling`
and `C1-reference`, or `all`. It writes one report to a new file, or one report per
case to a new folder, and exits with 1 when a played run differs from the saved one.

## Complete article reproduction

The data ZIP contains records, reports, figures, a license and an inventory, but
no source code or nested client archive. Do not copy an old `source/` folder over
this checkout. Keep all newly generated outputs outside the extracted data directory.

After the three commands above, execute the client on the archived responses and
the controlled article examples:

```sh
uv run python -m examples.coordinated_planning.run --offline --case all \
  --archive ../Factory-Simulator-Reproduction.zip --output data/client-check
uv run python -m scripts.reproduction.article all \
  --data "$PACKAGE" --output data/article-check
```

Expected results: 483 logical requests pass the input audit; four client cases match
on 159 periods; eight saved-action replays match on 367 periods; 34 notice cases,
12 sensitivity cases and one continuation match the archive on result, periods and
world; the small examples agree and all six figures are generated. Numerical solver
diagnostics may differ within the documented tolerance; timings are excluded.
No command above needs credentials or makes paid model calls.

See [article procedures](article/README.md) for individual commands and evidence
boundaries. Original scientific results were generated with engine commit
`319489ac6f7c45ae022521681b1a93b5e9e01ecd`; the data archive records the commit of
its validation reports. Both commits belong to the earlier development history and
are not part of this repository. The simulator source (`src/`) of that engine commit
is identical to tag `v1.0.0`; only reproduction scripts, tests, examples and
documentation changed since. Historical reports describe their
original versions, not automatic validation of this checkout. In particular, the
18 November live A3 check belongs to the earlier client distribution; this migration
checks the repository client offline, without repeating live calls.
