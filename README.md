# Factory simulator

A factory simulator for research on agents. It models one factory over periods, serves
each run through HTTP and records enough data to replay it.

## What it is

- A factory with suppliers, customers, lines, warehouses and routes.
- Decisions made once per period by an agent or a person with an assistant.
- One fixed world for a manifest, scenario and seed.
- Profit and other measures recorded for every run.

## Install

You need Python 3.14 and uv.

```sh
git clone https://github.com/mchojna/factory-simulator.git
cd factory-simulator
uv sync
```

## Quick start

Start the HTTP service with a database in `data/records/`:

```sh
bash scripts/start_server.sh
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

## Language-model demos

[Demos](demos/README.md) include live model planning. Copy the
[environment template](.env.template) to `.env`, fill the selected provider key and
model, then follow the demo setup.

## Documentation

The [development documentation in English](docs/development/en/README.md) and
[development documentation in Polish](docs/development/pl/README.md) describe how to use
the simulator. The [documentation hub](docs/hub/README.md) links to both languages.

The development collection covers six sections:

- [Start](docs/development/en/start/overview.md): the simulator, a quick start and its
  concepts.
- [Rules](docs/development/en/rules/period.md): periods, decisions, information and
  factory rules.
- [Library](docs/development/en/library/example-factory.md): the example factory and
  scenarios.
- [Benchmark](docs/development/en/benchmark/playing-a-run.md): agents, optimizers,
  scores and the stress test.
- [Guides](docs/development/en/guides/writing-a-manifest.md): manifests and scenarios.
- [Reference](docs/development/en/reference/http-interface.md): the HTTP interface,
  fields, measures and limits.

Serve the documentation with `bash scripts/serve_docs.sh development`. Build the site with
`bash scripts/build_docs.sh site/public`.

## Changes and contributing

See the [changelog](CHANGELOG.md) and [contribution guide](CONTRIBUTING.md).

## License

MIT. See [the license](LICENSE).
