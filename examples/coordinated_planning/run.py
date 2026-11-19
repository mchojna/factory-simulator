"""The coordinated planning example: saved replies offline or paid requests live.

Examples:
    >>> sorted(CASES)
    ['A3', 'B3', 'C1', 'C2']
"""

import argparse
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from examples.coordinated_planning import MODEL
from examples.coordinated_planning.evidence import (
    case_folder,
    extract,
    offline_network,
)
from examples.coordinated_planning.files import write_json
from examples.coordinated_planning.play import CASES, play_case
from examples.coordinated_planning.recorded import RecordedProvider
from examples.coordinated_planning.transport import MAX_CAP_USD, Budget, LiveProvider
from factory_simulator.api.core.config import Settings
from factory_simulator.api.main import create_app
from factory_simulator.benchmark.client import JsonObject

# The files of a played case that equal those of its saved case.
COMPARED = ("decisions", "periods", "result", "world")


def main(arguments: list[str] | None = None) -> None:
    """Play the selected cases offline from the archive or live with a budget.

    Args:
        arguments (list[str] | None, optional): The command line arguments; those of
            the process when not given.

    Examples:
        >>> main(["--output", "data/examples/coordinated-planning/offline"])
        Traceback (most recent call last):
        ...
        SystemExit: 2
    """
    parser = _parser()
    options = parser.parse_args(arguments)
    if options.live and options.archive is not None:
        parser.error("--archive: applies only with --offline")
    archive: Path | None = options.archive
    if options.offline and archive is None:
        parser.error("--archive: is required with --offline")
    output = options.output.resolve()
    if output.exists():
        parser.error(f"--output: already exists: {output}")
    cases = list(CASES) if options.case == "all" else [options.case]
    rates = [
        options.budget_usd,
        options.input_usd_per_million,
        options.output_usd_per_million,
    ]
    key = ""
    if options.live:
        if not all(rates):
            parser.error(
                "--live: requires --budget-usd, --input-usd-per-million and "
                "--output-usd-per-million"
            )
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            parser.error("--live: requires an exported OPENAI_API_KEY")
    output.mkdir(parents=True)
    if archive is not None:
        _play_offline(archive, cases, output)
    else:
        _play_live(key, rates, cases, output)


def _parser() -> argparse.ArgumentParser:
    """Build the command line parser of the example.

    Returns:
        argparse.ArgumentParser: The parser with the mode, case, output, budget and
            archive arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--offline", action="store_true", help="give the saved replies of the archive"
    )
    mode.add_argument(
        "--live", action="store_true", help="send paid requests to the model"
    )
    parser.add_argument("--case", choices=[*CASES, "all"], default="A3")
    parser.add_argument(
        "--output", type=Path, required=True, help="a new directory of the records"
    )
    parser.add_argument(
        "--budget-usd", help=f"the spending cap of --live, at most {MAX_CAP_USD} USD"
    )
    parser.add_argument(
        "--input-usd-per-million", help="the current price of input tokens"
    )
    parser.add_argument(
        "--output-usd-per-million",
        help="the current price of output tokens, reasoning included",
    )
    parser.add_argument(
        "--archive", type=Path, help="the evidence archive of --offline"
    )
    return parser


def _client_app(output: Path) -> TestClient:
    """Give an in-process client of the HTTP interface with its database in output.

    Args:
        output (Path): The output directory.

    Returns:
        TestClient: The client; its base URL is the HTTP interface.
    """
    settings = Settings(
        database_url=f"duckdb:///{output / 'runs.duckdb'}", load_examples=False
    )
    return TestClient(create_app(settings), base_url="http://testserver/api/v1")


def _play_offline(archive: Path, cases: list[str], output: Path) -> None:
    """Play cases with the saved replies and compare them with the archive.

    Args:
        archive (Path): The evidence archive.
        cases (list[str]): The cases, in order.
        output (Path): The new output directory.

    Raises:
        RuntimeError: If a request or a played file differs from the archive.
    """
    summaries: JsonObject = {}
    with offline_network():
        package = extract(output / "evidence", archive)
        with _client_app(output) as client:
            for case in cases:
                saved = case_folder(package, case)
                provider = RecordedProvider(saved)
                print(f"{case}: playing the saved replies", flush=True)
                folder = output / case
                summaries[case] = play_case(client, case, provider, folder)
                provider.assert_complete()
                matched = {
                    name: _read(folder / f"{name}.json")
                    == _read(saved / f"{name}.json")
                    for name in COMPARED
                }
                if not all(matched.values()):
                    raise RuntimeError(f"{case}: played files differ: {matched}")
                write_json(
                    folder / "controller-verification.json",
                    {
                        "status": "exact",
                        "case": case,
                        "requests_matched": provider.index,
                        "matched": matched,
                        "new_model_calls": 0,
                        "method": (
                            "Archived replies fed through the integrated controller; "
                            "simulator re-executed."
                        ),
                    },
                )
                print(f"{case}: exact", flush=True)
        write_json(
            output / "summary.json",
            {"mode": "offline", "cases": summaries, "new_model_calls": 0},
        )


def _play_live(key: str, rates: list[str], cases: list[str], output: Path) -> None:
    """Play cases with paid requests, sharing one budget.

    Args:
        key (str): The OpenAI credential.
        rates (list[str]): The cap in USD and the USD per million input and output
            tokens.
        cases (list[str]): The cases, in order.
        output (Path): The new output directory.
    """
    budget = Budget.create(output / "budget.json", *rates)
    summaries: JsonObject = {}
    with _client_app(output) as client:
        provider = LiveProvider(budget, output, key)
        for case in cases:
            provider.case = case
            print(f"{case}: live model {MODEL}; cap {rates[0]} USD", flush=True)
            summaries[case] = play_case(client, case, provider, output / case)
            write_json(
                output / "summary.json",
                {
                    "mode": "live",
                    "cases": summaries,
                    "cost_estimate_usd": budget.state["spent"],
                    "occupied_usd": str(budget.total()),
                },
            )


def _read(path: Path) -> object:
    """Give the JSON value of a file.

    Args:
        path (Path): The JSON file.

    Returns:
        object: The value.
    """
    return json.loads(path.read_text())


if __name__ == "__main__":
    main()
