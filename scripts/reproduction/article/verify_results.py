"""Reproduce the archived article evidence with the current repository."""

from datetime import UTC
from pathlib import Path
from typing import Any, cast


def check_case_inventory(
    expected: set[str],
    actual: set[str],
    archived_records: Path,
    records: Path,
    label: str,
) -> None:
    """Require every archived case in both the summary and output records.

    Raises:
        AssertionError: If expected cases are empty, missing or supplemented.
    """

    def names(root: Path) -> set[str]:
        return {
            p.relative_to(root).with_suffix("").as_posix() for p in root.rglob("*.json")
        }

    expected_files, actual_files = names(archived_records), names(records)
    if not expected or not expected <= expected_files:
        raise AssertionError(f"{label} archive inventory differs: missing case records")
    # Record folders also contain the archived manifests and scenarios.
    for source, required, found in (
        ("summary", expected, actual),
        ("records", expected_files, actual_files),
    ):
        if found != required:
            raise AssertionError(
                f"{label} {source} inventory differs: "
                f"missing={sorted(required - found)}, extra={sorted(found - required)}; "
                f"expected {len(required)} entries"
            )


def main() -> None:
    """Reproduce this archived example."""
    import csv
    import json
    import platform
    import sys
    import time
    from datetime import datetime
    from decimal import Decimal
    from importlib import metadata

    started: Any = time.perf_counter()

    def installed_version(name: Any) -> Any:
        """Apply the archived example procedure."""
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    from .context import DATA
    from .context import OUTPUT as WORK

    B = WORK / "notice"
    P = B

    def read(n: Any) -> Any:
        """Apply the archived example procedure."""
        root = DATA / "notice" if n.startswith("recorded") else P
        return json.loads((root / n).read_text())

    res: Any = read("results.json")
    ext: Any = read("extension-results.json")
    check_case_inventory(
        set(read("recorded-results.json")["cases"]),
        set(res["cases"]),
        DATA / "notice/recorded",
        B / "records",
        "notice matrix",
    )
    check_case_inventory(
        set(read("recorded-extension-results.json")["cases"]),
        set(ext["cases"]),
        DATA / "notice/recorded-extension",
        B / "extension-records",
        "sensitivity extension",
    )
    report: Any = {
        "report_schema_version": 2,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "virtual_environment": sys.prefix != sys.base_prefix,
            "packages": {
                name: installed_version(name)
                for name in ["numpy", "scipy", "pytest", "matplotlib"]
            },
        },
        "fresh_archive_extraction": None,
        "fresh_dependency_installation": None,
        "network_attempts": None,
        "metadata_scope": "Environment describes this verification process, not the earlier simulations. Extraction, installation freshness and network activity are not measured by this file-only verifier; null means unknown. Counts are derived from the compared records, not proof that this verifier executed simulations.",
        "matrix": {},
        "extension": {},
    }
    period_counts: Any = {"matrix": 0, "extension": 0, "continuation": 0}
    for name in res["cases"]:
        a: Any = read("recorded/" + name + ".json")
        b: Any = read("records/" + name + ".json")
        checks = {k: a[k] == b[k] for k in ["result", "periods", "world"]}
        assert all(checks.values()), (name, checks)
        report["matrix"][name] = checks
        period_counts["matrix"] += len(b["periods"])
    diffs: Any = []
    timings: Any = []

    def compare(a: Any, b: Any, path: Any = "") -> Any:
        """Compare diagnostic records with an explicit numeric tolerance.

        Raises:
            AssertionError: If structure or values differ beyond tolerance.
        """
        if path.rsplit("/", 1)[-1] in [
            "elapsed_seconds",
            "seconds",
            "time_limit_seconds",
        ]:
            timings.append(path)
            return
        if type(a) is not type(b) and (
            not (isinstance(a, (int, float)) and isinstance(b, (int, float)))
        ):
            raise AssertionError((path, "types differ"))
        if isinstance(a, dict):
            a = cast(dict[str, Any], a)
            b = cast(dict[str, Any], b)
            assert a.keys() == b.keys(), path
            for k in a:
                compare(a[k], b[k], path + "/" + k)
        elif isinstance(a, list):
            a = cast(list[Any], a)
            b = cast(list[Any], b)
            assert len(a) == len(b), path
            for i, (x, y) in enumerate(zip(a, b, strict=False)):
                compare(x, y, path + "/" + str(i))
        elif a != b:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta: Any = abs(a - b)
                diffs.append(
                    {"path": path, "old": a, "new": b, "absolute_difference": delta}
                )
                assert delta <= 1e-07, (path, delta)
            else:
                raise AssertionError((path, a, b))

    compare(read("recorded-diagnostics.json"), read("diagnostics.json"))
    compare(
        read("recorded-equal_plan_continuation.json"),
        read("equal_plan_continuation.json"),
        "/continuation",
    )
    report["numeric_comparison"] = {
        "tolerance": 1e-07,
        "differences": diffs,
        "max_absolute_difference": max(
            [x["absolute_difference"] for x in diffs], default=0
        ),
        "ignored_elapsed_timing_paths": timings,
    }
    report["controlled_continuation_exact"] = {
        k: read("recorded-equal_plan_continuation.json")[k]
        == read("equal_plan_continuation.json")[k]
        for k in ["result", "periods", "world"]
    }
    assert all(report["controlled_continuation_exact"].values())
    report["source_unchanged"] = read("source_hashes_before.json") == read(
        "source_hashes_after.json"
    )
    assert report["source_unchanged"]
    report["diagnostic_question_count"] = len(read("diagnostics.json")["questions"])
    rows: Any = []
    for label in [
        "zero",
        "pct_0.02",
        "pct_0.1",
        "pct_0.2",
        "library_like",
        "pct_1",
        "pct_2",
        "pct_5",
    ]:
        data = res if label in ["zero", "library_like"] else ext
        x: Any = data["cases"][label + "-notice2-buffered"]
        y: Any = data["cases"][label + "-notice2-full_horizon"]
        rows.append(
            {
                "rate": label,
                "buffered_service": x["measures"]["units_shipped_on_time"],
                "buffered_profit": x["profit"],
                "full_horizon_service": y["measures"]["units_shipped_on_time"],
                "full_horizon_profit": y["profit"],
                "profit_difference": str(
                    Decimal(str(y["profit"])) - Decimal(str(x["profit"]))
                ),
            }
        )
    report["sensitivity_rows"] = rows
    for name in ext["cases"]:
        expected: Any = read("recorded-extension/" + name + ".json")
        actual: Any = read("extension-records/" + name + ".json")
        checks = {k: expected[k] == actual[k] for k in ["result", "periods", "world"]}
        assert all(checks.values()), (name, checks)
        report["extension"][name] = checks
        period_counts["extension"] += len(actual["periods"])
    period_counts["continuation"] = len(read("equal_plan_continuation.json")["periods"])
    report.update(
        compared_matrix_runs=len(report["matrix"]),
        compared_extension_runs=len(report["extension"]),
        compared_continuation_runs=1,
        compared_closed_periods=period_counts,
        total_compared_closed_periods=sum(period_counts.values()),
        verification_elapsed_seconds=time.perf_counter() - started,
        status="PASS",
    )
    (B / "verification.json").write_text(json.dumps(report, indent=2))
    with (B / "sensitivity.csv").open("w") as f:
        w: Any = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(
        json.dumps(
            {
                "matrix_exact": len(report["matrix"]),
                "continuation_exact": report["controlled_continuation_exact"],
                "numeric_differences": diffs,
                "timings_excluded": len(timings),
                "rows": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
