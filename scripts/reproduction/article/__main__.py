"""Run the article examples without modifying the data archive or calling a model."""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from examples.coordinated_planning.evidence import (
    inventory_differences,
    offline_network,
)

COMMANDS = {
    "notice": [
        "run_audit",
        "diagnose_plans",
        "check_equal_plan_continuation",
        "run_sensitivity_extension",
        "verify_results",
    ],
    "examples": ["run_demonstrations", "run_allocation"],
    "figures": ["make_figures_1_4_6", "make_figure5"],
}


def compare_examples(data: Path, output: Path) -> None:
    """Compare the small example outcomes with the archived JSON records.

    Raises:
        AssertionError: If the record inventory or a result, period record or world differs.
    """
    summaries = {
        Path("examples/order-fulfilment/demonstration-results.json"),
        Path("examples/reference/reference-example-results.json"),
    }

    def records(root: Path) -> set[Path]:
        return {
            path.relative_to(root) for path in (root / "examples").rglob("*.json")
        } - summaries

    expected_files, actual_files = records(data), records(output)
    if not expected_files or actual_files != expected_files:
        missing = sorted(str(p) for p in expected_files - actual_files)
        extra = sorted(str(p) for p in actual_files - expected_files)
        raise AssertionError(
            f"example inventory differs: missing={missing}, extra={extra}; "
            f"expected {len(expected_files)} records"
        )
    checks: dict[str, bool] = {}
    for relative in sorted(expected_files):
        actual = output / relative
        expected = data / relative
        if not expected.is_file():
            raise AssertionError(f"missing archived example: {relative}")
        saved = json.loads(expected.read_text())
        current = json.loads(actual.read_text())
        if actual.name.startswith("micro-") and "result" in current:
            for key in ("result", "periods", "world"):
                checks[f"{relative}:{key}"] = saved[key] == current[key]
        else:
            checks[str(relative)] = saved == current
    (output / "example-comparison.json").write_text(json.dumps(checks, indent=2))
    if not checks or not all(checks.values()):
        raise AssertionError("article examples differ; see example-comparison.json")


def validate_paths(data: Path, output: Path) -> None:
    """Reject overlapping paths and changed evidence before running any code.

    Raises:
        ValueError: If paths overlap or the data manifest differs.
        FileExistsError: If the output folder already exists.
    """
    if data == output or data in output.parents or output in data.parents:
        raise ValueError("data and output must be separate, non-overlapping folders")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    differences = inventory_differences(data)
    if differences:
        raise ValueError(f"data inventory differs: {differences[:5]}")


def main() -> None:
    """Parse the selected offline command and write its outputs to a new folder.

    Raises:
        RuntimeError: If checks are disabled or input data change.
    """
    if not __debug__:
        raise RuntimeError("run without -O: scientific assertion checks are required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*COMMANDS, "all"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    validate_paths(data, output)
    output.mkdir(parents=True)
    (output / "notice").mkdir()
    os.environ["FACTORY_ARTICLE_DATA"] = str(data)
    os.environ["FACTORY_ARTICLE_OUTPUT"] = str(output)
    # Small article factories reuse the repository's tested fixtures.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
    sys.dont_write_bytecode = True
    groups = COMMANDS if args.command == "all" else [args.command]
    with offline_network():
        for group in groups:
            for name in COMMANDS[group]:
                module = importlib.import_module(f"scripts.reproduction.article.{name}")
                print(f"RUN {name}", flush=True)
                (module.run if name == "run_audit" else module.main)()
            if group == "examples":
                compare_examples(data, output)
    if inventory_differences(data):
        raise RuntimeError("input data changed during reproduction")
    print("PASS: data unchanged; article commands completed without network access")


if __name__ == "__main__":
    main()
