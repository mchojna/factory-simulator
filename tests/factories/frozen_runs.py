import hashlib
from pathlib import Path
from random import Random
from typing import Any

from factories.bodies import example_bodies
from factories.client import api_client, get, start_run, submit
from factories.record import records, rows_of_run
from factories.strategies import random_run
from factories.worlds import example_world
from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.run import Trace

# The folder of the frozen runs.
FROZEN = Path(__file__).parents[1] / "frozen"

# The frozen runs that a change other than a change of the rules or the examples must
# replay.
FROZEN_RUNS = [
    (scenario_name, seed)
    for scenario_name in ("steady-market", "surge-and-breakdown", "regional-crisis")
    for seed in (0, 1)
]


# The file of the frozen run of a scenario and a seed.
def frozen_file(scenario_name: str, seed: int) -> Path:
    return FROZEN / f"{scenario_name}-{seed}.json"


# The columns of `runs` that name the versions and the machine, not the run.
VERSION_COLUMNS = (
    "package_version",
    "numpy_version",
    "python_version",
    "pydantic_version",
    "duckdb_version",
    "platform",
)


# The decisions of every period of a frozen run, drawn from its seed.
def frozen_decisions(scenario_name: str, seed: int) -> list[list[dict[str, Any]]]:
    world = example_world(scenario_name, seed)
    _, steps = random_run(world, Random(seed))
    return [decisions for _, decisions, _ in steps]


# Run the example over HTTP and give the SHA-256 of every response and table. Each value
# is written as canonical JSON with the run identifier replaced by `<run>` and the
# version columns left out.
def frozen_digests(
    scenario_name: str,
    seed: int,
    decisions: list[list[dict[str, Any]]],
    *,
    include_trace: bool = False,
) -> dict[str, Any]:
    with api_client() as client:
        run = start_run(client, *example_bodies(scenario_name), seed=seed)
        responses: list[Any] = [run]
        for period, period_decisions in enumerate(decisions, start=1):
            status, answer = submit(client, run["id"], period, period_decisions)
            assert status == 200, answer
            responses.append(answer)
        responses.append(get(client, f"/runs/{run['id']}/result")[1])
        tables = rows_of_run(client, run["id"])
        if include_trace:
            tables["traces"] = [
                {key: value for key, value in row.items() if key != "run_id"}
                for row in records(client, Trace, run_id=run["id"])
            ]
    tables["runs"] = [
        {key: value for key, value in row.items() if key not in VERSION_COLUMNS}
        for row in tables["runs"]
    ]

    def digest(value: object) -> str:
        text = write_json(value).decode().replace(run["id"], "<run>")
        return hashlib.sha256(text.encode()).hexdigest()

    return {
        "responses": [digest(response) for response in responses],
        "tables": {name: digest(rows) for name, rows in sorted(tables.items())},
    }
