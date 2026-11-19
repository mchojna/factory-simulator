"""The replay of saved decisions: one saved run played again and compared, as JSON.

Examples:
    >>> CASES["B-rolling"]
    ('steady-market', 52)
"""

import argparse
import importlib.metadata
import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from examples.coordinated_planning.evidence import CASE_FOLDERS, offline_network
from examples.coordinated_planning.play import start_scenario
from examples.utils.cli import REPOSITORY
from factory_simulator.api.core.config import Settings
from factory_simulator.api.main import create_app
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject

# The scenario and horizon of each saved run: the four runs of the coordinated agent
# and the four runs of the references.
CASES = {
    "A3": ("small", 3),
    "B3": ("steady-market", 52),
    "C1": ("notice", 52),
    "C2": ("notice", 52),
    "B-rolling": ("steady-market", 52),
    "B-reference": ("steady-market", 52),
    "C1-rolling": ("notice", 52),
    "C1-reference": ("notice", 52),
}
# The folder of each saved run in the package.
RECORD_FOLDERS = {
    **CASE_FOLDERS,
    **{name: f"references/runs/{name}" for name in CASES if "-" in name},
}
# The files of a saved run.
SAVED = ("decisions", "start", "periods", "result", "world")


def normalized(value: object) -> object:
    """Give a value as it reads back from JSON, decimals and dates as text.

    Args:
        value (object): The value.

    Returns:
        object: The value written as JSON and read again.

    Examples:
        >>> from decimal import Decimal
        >>> normalized({"cash": Decimal("1.50")})
        {'cash': '1.50'}
    """
    return json.loads(json.dumps(value, default=str))


def replay(case: str, record: Path) -> JsonObject:
    """Play the saved decisions of a run again and compare the run with its record.

    Args:
        case (str): The saved run, a key of `CASES`.
        record (Path): The folder of the saved run.

    Returns:
        dict[str, Any]: The case, its periods, `exact` or `mismatch`, and whether the
            periods, result, world and period counts match.

    Raises:
        ValueError: If the record is not a complete run.
        RuntimeError: If the description differs or the decisions do not finish the
            run.

    Examples:
        >>> replay("A3", Path("missing"))  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        FileNotFoundError: [Errno 2] No such file or directory: ...
    """
    saved = {name: json.loads((record / f"{name}.json").read_text()) for name in SAVED}
    scenario_name, horizon = CASES[case]
    if len(saved["decisions"]) != horizon:
        raise ValueError(f"{record}: decisions do not cover {horizon} periods")
    with (
        offline_network(),
        tempfile.TemporaryDirectory(prefix="factory-record-replay-") as folder,
    ):
        settings = Settings(
            database_url=f"duckdb:///{Path(folder) / 'replay.duckdb'}",
            load_examples=False,
        )
        with TestClient(
            create_app(settings), base_url="http://testserver/api/v1"
        ) as client:
            run = start_scenario(client, scenario_name)
            run_id = str(run["id"])
            if normalized(run["description"]) != saved["start"]["description"]:
                raise RuntimeError(f"{case}: description differs from the record")
            answer: JsonObject = {}
            for entry in saved["decisions"]:
                answer = benchmark.send(
                    client, "POST", f"/runs/{run_id}/decisions", entry
                )
            if not answer.get("finished", False):
                raise RuntimeError(f"{case}: saved decisions do not finish the run")
            played = {
                "periods": benchmark.read_periods(client, run_id),
                "result": benchmark.read(client, f"/runs/{run_id}/result"),
                "world": benchmark.read_world(client, run_id),
            }
    matched = {name: normalized(value) == saved[name] for name, value in played.items()}
    matched["period_count"] = len(played["periods"]) == horizon
    matched["saved_period_count"] = len(saved["periods"]) == horizon
    return {
        "case": case,
        "periods": len(saved["decisions"]),
        "status": "exact" if all(matched.values()) else "mismatch",
        "matched": matched,
        "model_calls": 0,
        "optimiser_calls": 0,
        "python": sys.version,
        "source": str(REPOSITORY),
    }


def main(arguments: list[str] | None = None) -> None:
    """Replay one saved run or all eight, write each report to a new file and print it.

    Args:
        arguments (list[str] | None, optional): The command line arguments; those of
            the process when not given.

    Raises:
        SystemExit: If the arguments are invalid, or with 1 when a run differs.

    Examples:
        >>> main([])
        Traceback (most recent call last):
        ...
        SystemExit: 2
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[*CASES, "all"], required=True)
    parser.add_argument(
        "--package-root", type=Path, required=True, help="the extracted package"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="a new file of the report, or a new folder of the reports of all",
    )
    options = parser.parse_args(arguments)
    if options.output.exists():
        parser.error(f"--output: already exists: {options.output}")
    version = importlib.metadata.version("factory-simulator")
    if version != "1.0.0":
        parser.error(f"factory-simulator: version {version} is not 1.0.0")
    cases = list(CASES) if options.case == "all" else [options.case]
    if options.case == "all":
        options.output.mkdir(parents=True)
    else:
        options.output.parent.mkdir(parents=True, exist_ok=True)
    reports: list[JsonObject] = []
    for case in cases:
        report = replay(case, options.package_root / RECORD_FOLDERS[case])
        path = (
            options.output / f"{case}.json" if options.case == "all" else options.output
        )
        with path.open("x") as stream:
            json.dump(report, stream, indent=2)
        print(json.dumps(report), flush=True)
        reports.append(report)
    if any(report["status"] != "exact" for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
