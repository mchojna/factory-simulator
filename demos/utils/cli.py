"""The demo command line: shared inputs and output paths.

Examples:
    >>> demo_parser("run-without-decisions").parse_args([]).seed
    7
"""

import argparse
import json
from pathlib import Path

import httpx2 as httpx

from demos import DEFAULT_SEED
from demos.utils import DEFAULT_SERVER
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject

REPOSITORY = Path(__file__).resolve().parents[2]


def demo_parser(
    name: str,
    *,
    accepts_run_id: bool = False,
    accepts_archive: bool = False,
    accepts_summary: bool = False,
) -> argparse.ArgumentParser:
    """Build the shared command line parser for a demo.

    Args:
        name (str): The descriptive demo name.
        accepts_run_id (bool, optional): Whether the demo resumes a stored run.
        accepts_archive (bool, optional): Whether the demo reads a finished archive.
        accepts_summary (bool, optional): Whether the demo reads a saved summary of a
            model demo.

    Returns:
        argparse.ArgumentParser: The parser with the common API, seed and output
            arguments.

    Examples:
        >>> demo_parser("run-without-decisions").parse_args([]).seed
        7
    """
    parser = argparse.ArgumentParser(prog=name)
    if not accepts_archive and not accepts_summary:
        parser.add_argument("--server", default=DEFAULT_SERVER)
        parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--output", type=Path, default=REPOSITORY / "data" / "demos" / name
    )
    if accepts_run_id:
        parser.add_argument("--run-id")
    if accepts_archive:
        parser.add_argument("--archive", type=Path, required=True)
    if accepts_summary:
        parser.add_argument("--summary", type=Path, required=True)
    return parser


def save_finished_run(
    client: httpx.Client,
    name: str,
    run: JsonObject,
    result: JsonObject,
    output: Path,
    details: JsonObject | None = None,
) -> Path:
    """Save a finished run summary and its HTTP export.

    Args:
        client (httpx.Client): The API client.
        name (str): The descriptive demo name.
        run (dict[str, Any]): The finished run's public start response.
        result (dict[str, Any]): The result read from the API.
        output (Path): The root output directory for this demo.
        details (dict[str, Any] | None, optional): Demo-specific observations.

    Returns:
        Path: The written summary file.

    Raises:
        FileExistsError: If an output directory for this run already exists.
        RuntimeError: If the API refuses its finished-run export.

    Examples:
        >>> import httpx2 as httpx
        >>> def respond(request: httpx.Request) -> httpx.Response:
        ...     if request.url.path.endswith("/periods"):
        ...         return httpx.Response(200, text='{"periods":[{"period":1}]}')
        ...     return httpx.Response(200, content=b"run archive")
        >>> transport = httpx.MockTransport(respond)
        >>> client = httpx.Client(transport=transport, base_url="http://server/api/v1")
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     path = save_finished_run(
        ...         client,
        ...         "demo",
        ...         {"id": "r-1", "scenario_id": "s-1"},
        ...         {"seed": 7, "profit": 12},
        ...         Path(folder),
        ...     )
        ...     json.loads(path.read_text())["periods"]
        1
    """
    run_id = str(run["id"])
    periods = benchmark.read_periods(client, run_id)
    response = client.get(f"/runs/{run_id}/export")
    if response.status_code >= 400:
        raise RuntimeError(
            f"GET /runs/{run_id}/export: {response.status_code} "
            f"{benchmark.detail_of(response)}"
        )
    folder = output / run_id
    if folder.exists():
        existing = {path.name for path in folder.iterdir()}
        if existing != {"checkpoint.json"}:
            raise FileExistsError(f"output already exists: {folder}")
    else:
        folder.mkdir(parents=True, exist_ok=False)
    summary: JsonObject = {
        "demo": name,
        "run_id": run_id,
        "scenario_id": run["scenario_id"],
        "seed": result["seed"],
        "periods": len(periods),
        "profit": result["profit"],
        "result": result,
        "details": details or {},
    }
    summary_path = folder / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    (folder / f"{run_id}.zip").write_bytes(response.content)
    return summary_path


def save_checkpoint(
    name: str, run: JsonObject, seed: int, observation: JsonObject, output: Path
) -> Path:
    """Save the identifier and next period of a suspended demo run.

    Args:
        name (str): The descriptive demo name.
        run (dict[str, Any]): The run being paused.
        seed (int): The run seed.
        observation (dict[str, Any]): The next observation.
        output (Path): The root output directory for this demo.

    Returns:
        Path: The written checkpoint file.

    Raises:
        FileExistsError: If an output directory for this run already exists.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     path = save_checkpoint(
        ...         "resume-a-run",
        ...         {"id": "r-1", "scenario_id": "s-1"},
        ...         7,
        ...         {"period": 2},
        ...         Path(folder),
        ...     )
        ...     path.name
        'checkpoint.json'
    """
    run_id = str(run["id"])
    folder = output / run_id
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / "checkpoint.json"
    path.write_text(
        json.dumps(
            {
                "demo": name,
                "run_id": run_id,
                "scenario_id": run["scenario_id"],
                "seed": seed,
                "next_period": observation["period"],
            },
            indent=2,
        )
        + "\n"
    )
    return path


def write_inspection(name: str, run_id: str, record: JsonObject, output: Path) -> Path:
    """Write an offline inspection of the export of one finished run.

    Args:
        name (str): The descriptive demo name.
        run_id (str): The run identifier in the export.
        record (dict[str, Any]): The inspection of the export.
        output (Path): The root output directory for this demo.

    Returns:
        Path: The written inspection file.

    Raises:
        FileExistsError: If an output directory for this run already exists.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     path = write_inspection(
        ...         "inspect-a-record", "r-1", {"seed": 7}, Path(folder)
        ...     )
        ...     json.loads(path.read_text())["seed"]
        7
    """
    folder = output / run_id
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / "inspection.json"
    path.write_text(json.dumps({"demo": name, **record}, indent=2) + "\n")
    return path
