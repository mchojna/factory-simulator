import subprocess
from pathlib import Path

import pytest
from factories import (
    api_client,
    database_file,
    example_scenario,
    get,
    post,
    read_answer,
    run_to_the_end,
    served_app,
)

from factory_simulator.api.core.json import write_json

ROOT = Path(__file__).parents[3]
SEED = 3


def install_the_wheel(folder: Path) -> Path:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(folder)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    [wheel] = folder.glob("*.whl")
    environment = folder / "environment"
    subprocess.run(["uv", "venv", str(environment)], check=True, capture_output=True)
    python = environment / "bin" / "python"
    # The modules are compiled here, so the server that serves them starts within
    # its wait without compiling them.
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--compile-bytecode",
            "--python",
            str(python),
            str(wheel),
        ],
        check=True,
        capture_output=True,
    )
    return python


@pytest.mark.slow
def test_an_installed_wheel_serves_the_example_for_a_whole_run():
    with database_file() as url:
        python = install_the_wheel(Path(url.removeprefix("duckdb:///")).parent)
        with served_app(url, python, load_examples=True) as client:
            listed = read_answer(client.get("/api/v1/manifests"))
            [summary] = listed["manifests"]
            body = write_json(example_scenario())
            scenario = read_answer(
                client.post(
                    f"/api/v1/manifests/{summary['id']}/scenarios", content=body
                )
            )
            start = write_json({"scenario_id": scenario["id"], "seed": SEED})
            run = read_answer(client.post("/api/v1/runs", content=start))
            for period in range(1, 53):
                submission = write_json({"period": period, "decisions": []})
                client.post(f"/api/v1/runs/{run['id']}/decisions", content=submission)
            finished = read_answer(client.get(f"/api/v1/runs/{run['id']}"))
            served = read_answer(client.get(f"/api/v1/runs/{run['id']}/result"))
    with api_client(load_examples=True) as client:
        path = f"/manifests/{summary['id']}/scenarios"
        _, in_process_scenario = post(client, path, example_scenario())
        _, in_process_run = post(
            client, "/runs", {"scenario_id": in_process_scenario["id"], "seed": SEED}
        )
        run_to_the_end(client, in_process_run)
        _, in_process = get(client, f"/runs/{in_process_run['id']}/result")

    assert summary["name"] == "Electronics factory with economies of scale"
    assert finished["finished"]
    assert served == in_process
