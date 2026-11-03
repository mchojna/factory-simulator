# Factory simulator

A factory simulator for research on agents. It models one factory over periods, serves
each run through HTTP and records enough data to replay it.

## What it is

- A factory with suppliers, customers, lines, warehouses and routes.
- Decisions made once per period by an agent or a person with an assistant.
- One fixed world for a manifest, scenario and seed.
- Profit and other measures recorded for every run.

## Install

Version **1.0.0** requires Python 3.14. Install the release with uv:

```sh
git clone https://github.com/mchojna/factory-simulator.git
cd factory-simulator
git checkout v1.0.0
uv sync --locked --no-default-groups
```

For pip, create a virtual environment and install the locked base dependencies and
the package from the repository root:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps .
```

The base simulator and optimizers need no model credentials. Provider setup for the
language-model examples is in [examples](examples/README.md).

## Quick start

Start the HTTP service with a database in `data/records/`:

```sh
bash scripts/start_server.sh
```

For a pip installation, start the service from the repository root with:

```sh
mkdir -p data/records
FACTORY_SIMULATOR_DATABASE_URL=duckdb:///data/records/runs.duckdb \
  python -m uvicorn factory_simulator.api.main:app
```

In another terminal, run a no-decisions agent against the example factory:

```python
import json
from decimal import Decimal
from urllib.request import Request, urlopen

api = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        api + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        return json.loads(response.read(), parse_float=Decimal)


factory = call("GET", "/manifests")["manifests"][0]
scenarios = call("GET", f"/manifests/{factory['id']}/scenarios")["scenarios"]
scenario = next(item for item in scenarios if item["name"] == "steady-market")
run = call("POST", "/runs", {"scenario_id": scenario["id"], "seed": 7})
observation = call("GET", f"/runs/{run['id']}/observation")

while True:
    result = call(
        "POST",
        f"/runs/{run['id']}/decisions",
        {"period": observation["period"], "decisions": []},
    )
    if result.get("finished"):
        break
    observation = result

print(call("GET", f"/runs/{run['id']}/result")["profit"])
```

The program prints `-709331.2306` for the example factory, `steady-market` and seed 7.

## Language-model examples

[Examples](examples/README.md) include live model planning. Copy the
[environment template](.env.template) to `.env`, fill the selected provider key and
model, then follow the example setup.

## Documentation

The [documentation](docs/README.md) describes how to use the simulator.

The documentation covers six sections:

- [Start](docs/start/overview.md): the simulator, a quick start and its
  concepts.
- [Rules](docs/rules/period.md): periods, decisions, information and
  factory rules.
- [Library](docs/library/example-factory.md): the example factory and
  scenarios.
- [Benchmark](docs/benchmark/playing-a-run.md): agents, optimizers,
  scores and the stress test.
- [Guides](docs/guides/writing-a-manifest.md): manifests and scenarios.
- [Reference](docs/reference/http-interface.md): the HTTP interface,
  fields, measures and limits.

Install documentation tools with `uv sync --locked --group docs`.
Serve the documentation with `bash scripts/serve_docs.sh`. Build the site with
`bash scripts/build_docs.sh site/public`.

## Changes and contributing

See the [changelog](CHANGELOG.md) and [contribution guide](CONTRIBUTING.md).

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

MIT. See [the license](LICENSE.txt).
