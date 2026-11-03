# Contributing

This file holds the rules that bind every contribution. The rules of the factory
itself are in [the documentation](docs/README.md).

## Before you start

- Open an issue first for a new rule of the factory or a new decision. A change of a
  factory rule changes the results of runs, so it needs agreement before any code.
- Read the rule pages of [the documentation](docs/README.md)
  for the area you change.

## Set up

You need Python 3.14 and uv.

```sh
uv sync
uv run pre-commit install --install-hooks
```

`uv sync` installs the package and the development tools.

## Run

```sh
uv run pre-commit run --all-files
uv run pytest
uv run pytest -n 0
```

- `uv run pytest` runs one process per CPU. The whole suite takes about 13 minutes on
  14 CPUs.
- `uv run pytest -n 0` runs one process, for debugging.

Start the server with its database in `data/records/`:

```sh
bash scripts/start_server.sh
```

## Base requirements

`pyproject.toml` declares dependencies and `uv.lock` fixes their versions.
Regenerate the pip requirements after changing the base dependencies:

```sh
uv export --locked --no-default-groups --no-emit-project --no-header --format requirements-txt \
  --output-file requirements.txt
```

## Writing rules

These rules hold for every text: code, names, comments, docstrings, error messages,
documents, commit messages and pull requests.

- English everywhere.
- American spelling: `normalized`, `analyze`, `color`, `center`. A name of the
  manifest, the scenario, the HTTP interface or the record keeps its spelling, such as
  `catalogue`, `utilisation` and `distribution-centre`.
- The simplest language that is still exact: short sentences, one idea each, common
  words, a number instead of an adjective.
- The present tense: a text states what is. It never describes how something used to
  be or argues for a choice.
- ASCII only, checked by a hook, except author names in `README.md`,
  `CONTRIBUTING.md`, `LICENSE.txt`, `pyproject.toml` and `CITATION.cff`, and package metadata in `uv.lock`.
  No emoji, arrows, typographic quotes or dashes. Write `<=` and "then" in words.
- No separator lines of `-`, `=`, `#` or similar symbols.
- Diagrams are Mermaid, in a fenced `mermaid` block. The arrows of Mermaid syntax,
  such as `-->`, are allowed inside it.
- Plain full names, with the words of
  [the glossary](docs/reference/glossary.md). No abbreviations such as
  `qty` and no generic words such as `Manager` or `data`.

## Documentation

`docs/` holds the English source pages. Their terms come from the
[glossary](docs/reference/glossary.md).

Every page has one H1 title and a lead paragraph without a heading. H2 headings are
nouns or statements in sentence case, never questions. Nothing goes below H3. An
identifier appears in a heading only on a catalogue page. Pages follow one of these
skeletons:

| Kind | Skeleton |
| --- | --- |
| Rule | Lead, rule sections and `Worked example` as the last H2. |
| Guide | Lead, `Smallest example`, steps and `Errors`. |
| Reference | Lead and tables. |
| Catalogue | Lead, one H2 per group and one H3 per object. |

A page has about 300 lines at most. Mermaid diagrams use the shared palette below. A
link names the page or section, not its file. `tests/unit/test_docs.py` checks page
paths, heading levels, code blocks, diagrams, skeletons, palette classes and links
in the root files.

```text
classDef item fill:#3284D8,stroke:#3284D8,color:#000000
classDef place fill:#AF751D,stroke:#AF751D,color:#000000
classDef partner fill:#3D9250,stroke:#3D9250,color:#000000
classDef system fill:#9869DE,stroke:#9869DE,color:#000000
classDef disruption fill:#E8473C,stroke:#E8473C,color:#000000
```

| Class | Things | Fill |
| --- | --- | --- |
| `item` | Materials, components and products. | `#3284D8` |
| `place` | Lines and warehouses. | `#AF751D` |
| `partner` | Suppliers and customers. | `#3D9250` |
| `system` | Engine, HTTP interface, agent, harness and record. | `#9869DE` |
| `disruption` | Disruptions. | `#E8473C` |

Each fill has relative luminance from 0.219 to 0.221. Contrast against white is from
3.87 to 3.90 and against `#1E2029` from 4.16 to 4.20. Black text contrast is from
5.39 to 5.43. Use `flowchart` for recipes and flows, `sequenceDiagram` for the loop of
agent and server, `gantt` or `timeline` for periods and disruption windows,
`stateDiagram-v2` for orders and lines, `xychart-beta` for values over periods and
`gitGraph` for a fork.

## Building the docs

Install the documentation tools and serve the pages on a separate port from the
simulator server:

```sh
uv sync --group docs
bash scripts/serve_docs.sh
```

Build the site with the same strict check that CI runs:

```sh
bash scripts/build_docs.sh site/public
```

The `docs.yml` workflow builds the documentation on every
push to `main`. Its deploy job is skipped until the repository variable `PAGES_ENABLED`
is set to `true` after GitHub Pages is enabled.

## Code

- The simplest code that works. Nothing beyond what the change needs: no hooks,
  options or abstractions for a later need.
- Plain functions first. A class only for a data model or for state that functions
  cannot carry simply.
- Type hints everywhere; `pyright` runs in strict mode.
- A Google docstring on every module, class and public function, with every section
  that applies (`Args`, `Returns` or `Yields`, `Raises`, `Attributes`) and an
  `Examples` section that runs as a doctest. Every documented name carries its type.
- A module docstring opens with one line `The <thing>: <what it holds>.` A function
  docstring opens with a verb: `Give` for a value, `Tell whether` for a bool.
- An argument with a default is `name (type, optional): ...` and ends with
  `<value> when not given.`
- ruff formats the code of doctests like the code around it.
- An error message is `<path>: <problem>`: lower case, no full stop, a present-tense
  clause such as `is above max_quantity`, with comparisons in words.
- A decision the simulator does not accept is rejected, with a reason. An input or a
  submission that the simulator or a program does not take is refused.
- Imports are absolute and sit at the top of the module.
- A comment only for logic that is hard to see from the code.
- Code under `tests/` has no docstrings. A helper there has a `#` comment above it.
- A test name is a present-tense statement with numbers in digits:
  `test_a_buy_of_12_units_is_refused`.
- Every folder with code or pages has a `README.md`: an H1, a lead line,
  `## Contents` with one entry per tracked file or folder and `## Entry point` with the
  file to read first. An example has a guide README instead.

## Tests

- Three levels, each in its folder: `tests/unit/` (one function at a time),
  `tests/integration/` (requests to the HTTP interface) and `tests/e2e/` (whole runs
  driven over HTTP).
- A worked example checks a value computed by hand from the rule. A Hypothesis test
  states an invariant that holds for every valid input; it carries the marker
  `property`.
- A local run draws a tenth of the examples of each property; CI draws all of them.
  `CI=true uv run pytest -m property` draws what CI draws.
- A test that is not a property and takes more than a second carries the marker
  `slow`.
- Each test, and each Hypothesis example, runs a new lifespan of the application with
  its own database and `Server`; the tests of one process share one application, and a
  test that gives a database URL builds its own.
- Shared factories, strategies and helpers live in `tests/factories/`.
- Every change to logic comes with its tests in the same commit, and updates the
  earlier tests it breaks.
- The commit hook runs the unit tests and the doctests but `property` and `slow`. CI
  runs every test but the stress test: one job runs the rest, and 8 jobs share the
  properties and slow tests.
- The stress test in `tests/stress/` plays no decisions and the benchmark agents across
  the scenarios of the example manifest over many seeds, checks every run and writes a
  report into `data/reports/`. It carries the marker `stress`, and `-m "not stress"`
  in the `addopts` of `pyproject.toml` leaves it out of every other run. It starts by
  hand:

  ```sh
  uv run pytest tests/stress -m stress -n 0
  ```

  `--stress-seeds` sets the number of seeds, 20 by default; `--stress-scenarios` the
  scenarios, names separated by commas, `all` by default; `--stress-workers` the
  processes that play, the number of CPUs by default; `--stress-time-limit` the
  seconds every solve may take, 600 by default; and `--stress-evaluation`, off by
  default, plays the evaluation seeds 1000 to 1019 in place of 0 to n - 1.

## Results stay comparable

- A change of a rule of the factory, the observation, the measures or the record
  raises the version of the package and adds an entry to
  [the changelog](CHANGELOG.md).
- Every other change leaves every response and every row of the record identical.
  Frozen runs check this.
- The version of numpy changes only with a new version of the package.
- Every numeric parameter changes a named measure, and a test shows it.

## Commits and pull requests

- Conventional Commits: `type(scope): subject`. The types are `feat`, `fix`, `docs`,
  `refactor`, `test`, `chore`, `perf`, `build` and `ci`. The subject is imperative,
  lower case, without a full stop, at most 72 characters. A breaking change adds `!`
  before the colon.
- One commit does one thing.
- Never commit with `--no-verify`.
- The title of a pull request becomes its squash commit, so it follows the same rule.
- Fill the template of the pull request.

## Checks of a pull request

- The title is a Conventional Commit.
- Pre-commit runs over every file.
- The lock file matches `pyproject.toml`.
- ruff checks the format and the lint; pyright checks the types.
- Every test runs.
- The frozen world is drawn byte for byte the same on macOS and Windows.
- The built package installs into an empty environment and imports.

## Authors and citation

- Andrzej Wodecki
- Wojciech Godlewski
- Michał Chojna

If you use the simulator in research, cite the software version used in your study.
Citation metadata is in [CITATION.cff](CITATION.cff). The citation for this release is:

Wodecki, A., Godlewski, W., and Chojna, M. (2026). Factory Simulator (Version 1.0.0)
[Computer software]. https://github.com/mchojna/factory-simulator/releases/tag/v1.0.0

The [version 1.0.0 release](https://github.com/mchojna/factory-simulator/releases/tag/v1.0.0)
contains the source archive and Python package.

## License

Contributions are under the [MIT license](LICENSE.txt) of the repository.
