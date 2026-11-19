"""The audit of the recorded inputs: saved requests against saved runs, as JSON.

Examples:
    >>> walk({"orders": [{"id": "o-1"}]})[-1]
    ('/orders/0/id', 'id', 'o-1')
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from examples.coordinated_planning.evidence import CASE_FOLDERS

type JsonObject = dict[str, Any]

# The saved logical requests of each case.
CASES = [("A3", 9), ("B3", 156), ("C1", 159), ("C2", 159)]
# The cases of the coordinated agent and the reference each shares a world with.
MATCHED_REFERENCES = [("B3", "B-rolling"), ("C1", "C1-rolling"), ("C2", "C1-rolling")]
# What the audit does not show.
LIMITATIONS = [
    "Checks JSON message payloads, not arbitrary natural-language inference or every "
    "possible information channel.",
    "Logical request records are counted; transport attempts are not separately "
    "audited.",
    "Matching each observation to its own run does not imply identical observations "
    "after different controller actions.",
    "No causal attribution of the on-time performance difference is tested.",
    "The expected-demand rolling configuration was inspected in the archived source; "
    "no optimiser is executed here.",
]


def walk(value: object, path: str = "") -> list[tuple[str, str, object]]:
    """Give the path, key and value of every field of a JSON value, depth first.

    Args:
        value (object): The JSON value.
        path (str, optional): The path of the value; the root when not given.

    Returns:
        list[tuple[str, str, object]]: The path, key and value of every object field.

    Examples:
        >>> walk({"a": {"b": 1}})
        [('/a', 'a', {'b': 1}), ('/a/b', 'b', 1)]
    """
    fields: list[tuple[str, str, object]] = []
    if isinstance(value, dict):
        for key, child in cast(JsonObject, value).items():
            fields.append((f"{path}/{key}", key, child))
            fields.extend(walk(child, f"{path}/{key}"))
    elif isinstance(value, list):
        for position, child in enumerate(cast(list[object], value)):
            fields.extend(walk(child, f"{path}/{position}"))
    return fields


def observations_of(periods: list[JsonObject]) -> dict[int, JsonObject]:
    """Give the saved observation of each period.

    Args:
        periods (list[dict[str, Any]]): The closed periods.

    Returns:
        dict[int, dict[str, Any]]: The observation of the `build_observation` step,
            by period.

    Examples:
        >>> steps = [{"step": "build_observation", "observation": {"period": 1}}]
        >>> observations_of([{"period": 1, "steps": steps}])
        {1: {'period': 1}}
    """
    return {
        period["period"]: next(
            step["observation"]
            for step in period["steps"]
            if step["step"] == "build_observation"
        )
        for period in periods
    }


# The files an audit read, with their digests, and the checks it failed.
@dataclass(slots=True)
class _Package:
    root: Path
    digests: dict[str, str] = field(default_factory=dict[str, str])
    errors: list[str] = field(default_factory=list[str])

    def text(self, relative: str) -> str:
        raw = (self.root / relative).read_bytes()
        self.digests[relative] = hashlib.sha256(raw).hexdigest()
        return raw.decode("utf-8")

    def load(self, relative: str) -> Any:  # noqa: ANN401
        return json.loads(self.text(relative))

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def audit(root: Path) -> JsonObject:
    """Give the audit report of the recorded inputs of an extracted package.

    Args:
        root (Path): The extracted package folder.

    Returns:
        dict[str, Any]: The counts and findings of every case, the world and reference
            comparisons, the digests of the files read, the failed checks and the
            status, `PASS` or `FAIL`.

    Raises:
        OSError: If a file is missing.

    Examples:
        >>> audit(Path("missing"))  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        FileNotFoundError: [Errno 2] No such file or directory: ...
    """
    package = _Package(root)
    report: JsonObject = {
        "scope": "Structural audit of archived logical requests and saved outcomes",
        "engine_executed": False,
        "model_calls": 0,
        "cases": {case: _case_report(package, case, count) for case, count in CASES},
    }
    report["logical_requests_total"] = sum(
        case["logical_requests"] for case in report["cases"].values()
    )
    worlds = [
        package.load(f"references/runs/{name}/world.json")
        for name in ("B-rolling", "C1-rolling")
    ]
    differences = sorted(
        key
        for key in set(worlds[0]) | set(worlds[1])
        if worlds[0].get(key) != worlds[1].get(key)
    )
    package.check(differences == ["disruptions"], "Steady/notice world differences")
    disruptions = worlds[1]["disruptions"]
    package.check(
        len(disruptions) == 2
        and all(
            disruption["start"] == 10
            and disruption["duration"] == 32
            and disruption["visible"] == 6
            for disruption in disruptions
        ),
        "Notice disruption timing",
    )
    report["world_differences"] = differences
    report["notice_disruptions"] = disruptions
    report["matched_descriptions"] = {}
    for case, reference in MATCHED_REFERENCES:
        same = (
            package.load(f"{CASE_FOLDERS[case]}/start.json")["description"]
            == package.load(f"references/runs/{reference}/start.json")["description"]
        )
        package.check(same, f"{case}/{reference}: descriptions differ")
        report["matched_descriptions"][f"{case}/{reference}"] = same
    report["C1_comparison"] = _shipment_comparison(package)
    report["rolling_steady"] = _rolling_steady(package)
    report["limitations"] = LIMITATIONS
    report["input_sha256"] = package.digests
    report["errors"] = package.errors
    report["status"] = "FAIL" if package.errors else "PASS"
    return report


def _case_report(package: _Package, case: str, count: int) -> JsonObject:
    """Give the counts of one case after checking its requests against its run.

    Args:
        package (_Package): The package being audited.
        case (str): The case: A3, B3, C1 or C2.
        count (int): The saved logical requests the case has.

    Returns:
        dict[str, Any]: The requests, responses and periods, the first period with a
            visible disruption and the order lead times.
    """
    prefix = f"{CASE_FOLDERS[case]}/"
    rows = [
        json.loads(line)
        for line in package.text(f"{prefix}model-calls.jsonl").splitlines()
    ]
    requests = [row for row in rows if row["kind"] == "provider-request"]
    responses = [row for row in rows if row["kind"] == "provider-response"]
    observations = observations_of(package.load(f"{prefix}periods.json"))
    description = package.load(f"{prefix}start.json")["description"]
    package.check(len(requests) == count, f"{case}: request count")
    package.check(len(responses) == count, f"{case}: response count")
    package.check(
        len({request["call_id"] for request in requests}) == count,
        f"{case}: unique call IDs",
    )
    package.check(
        {request["period"] for request in requests} == set(observations),
        f"{case}: period coverage",
    )
    visible: list[int] = []
    lags: set[int] = set()
    for request in requests:
        period = request["period"]
        messages = request["messages"]
        package.check(
            request["request"]["messages"] == messages,
            f"{case}/{period}: request messages differ",
        )
        context = json.loads(messages[1]["content"])
        package.check(
            context["description"] == description,
            f"{case}/{period}: description differs",
        )
        package.check(
            context["observation"] == observations[period],
            f"{case}/{period}: observation differs",
        )
        for message in messages:
            try:
                parsed = json.loads(message["content"])
            except ValueError, TypeError:
                continue
            for path, key, value in walk(parsed):
                package.check(
                    key not in {"seed", "world"},
                    f"{case}/{period}: prohibited field {path}",
                )
                if key == "customer_orders":
                    for order in cast(list[JsonObject], value):
                        package.check(
                            order["arrival"] <= period,
                            f"{case}/{period}: future order {order['id']}",
                        )
                        lags.add(order["due"] - order["arrival"])
        if context["observation"]["disruptions"]:
            visible.append(period)
    first = min(visible) if visible else None
    package.check(
        first == (6 if case in {"C1", "C2"} else None), f"{case}: first disclosure"
    )
    return {
        "logical_requests": len(requests),
        "responses": len(responses),
        "periods": len(observations),
        "first_disclosure": first,
        "order_due_minus_arrival": sorted(lags),
    }


def _shipment_comparison(package: _Package) -> JsonObject:
    """Give the shipped and on-time shares of the ordered units of C1 and its reference.

    Args:
        package (_Package): The package being audited.

    Returns:
        dict[str, Any]: The units ordered, the shares in percent and the profit, by
            case.
    """
    summary = package.load("references/reference-summary.json")
    comparison: JsonObject = {}
    for case in ("C1", "C1-rolling"):
        totals = summary[case]["totals"]
        ordered = Decimal(totals["units_ordered"])
        comparison[case] = {
            "units_ordered": str(ordered),
            "shipped_ordered_pct": str(
                Decimal(totals["units_shipped"]) / ordered * 100
            ),
            "on_time_ordered_pct": str(
                Decimal(totals["units_shipped_on_time"]) / ordered * 100
            ),
            "profit": summary[case]["profit"],
        }
    return comparison


def _rolling_steady(package: _Package) -> JsonObject:
    """Give the order lead times and late periods of the steady-market reference.

    Args:
        package (_Package): The package being audited.

    Returns:
        dict[str, Any]: The orders by lead time and the periods with late shipments.
    """
    periods = package.load("references/runs/B-rolling/periods.json")
    lags: Counter[int] = Counter()
    late: list[int] = []
    for period, observation in observations_of(periods).items():
        for order in observation["customer_orders"]:
            if order["arrival"] == period:
                lags[order["due"] - order["arrival"]] += 1
    for period in periods:
        total = next(
            step["measures"]["total"]
            for step in period["steps"]
            if step["step"] == "close_period"
        )
        if Decimal(str(total["units_shipped_late"])) > 0:
            late.append(period["period"])
    package.check(dict(lags) == {1: 364, 2: 156}, "Steady order lead-time counts")
    package.check(
        len(late) == 40 and min(late) == 7 and max(late) == 52,
        "Steady late-shipment periods",
    )
    return {"order_lead_counts": dict(lags), "periods_with_late_shipments": late}


def main(arguments: list[str] | None = None) -> None:
    """Print the audit report and exit with 0 when it passes, else 1.

    Args:
        arguments (list[str] | None, optional): The command line arguments; those of
            the process when not given.

    Raises:
        SystemExit: Always, with 0 for `PASS` and 1 for `FAIL`.

    Examples:
        >>> main([])
        Traceback (most recent call last):
        ...
        SystemExit: 2
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root", type=Path, required=True, help="the extracted package"
    )
    options = parser.parse_args(arguments)
    try:
        report = audit(options.package_root)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        report = {
            "status": "FAIL",
            "error": str(error),
            "engine_executed": False,
            "model_calls": 0,
        }
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
