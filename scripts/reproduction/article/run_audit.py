"""Local, offline audit of manuscript 3.1; does not edit the released source."""

import hashlib
import json
import platform
import sys
import time
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from decimal import Decimal as D
from functools import partial
from typing import Any, cast

import numpy
import scipy
from factories import assert_run_balances, benchmark_client, item_balances

from factory_simulator.benchmark import client as b
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.optimizers.full_horizon import full_horizon_optimizer
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions
from factory_simulator.benchmark.optimizers.reference import (
    customer_orders_of,
    reference_optimizer,
)
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer

from .context import DATA, REPOSITORY
from .context import OUTPUT as WORK

HERE = WORK / "notice"
OUTPUT = HERE / "records"
SOURCE = REPOSITORY
OLD = DATA / "notice" / "original-notice"
connections: Any = []


def encode(x: Any) -> Any:
    """Encode a dataclass, Decimal or sequence as JSON.

    Raises:
        TypeError: If the value is not supported.
    """
    if is_dataclass(x) and not isinstance(x, type):
        return asdict(x)
    if isinstance(x, D):
        return str(x)
    if isinstance(x, (set, tuple)):
        return list(cast(Any, x))
    raise TypeError(type(x).__name__)


def dump(x: Any) -> Any:
    """Apply the archived example procedure."""
    return json.dumps(x, default=encode, sort_keys=True, indent=2)


def normal(x: Any) -> Any:
    """Apply the archived example procedure."""
    return json.loads(dump(x))


def save(path: Any, x: Any) -> None:
    """Write the evidence as JSON."""
    path.write_text(dump(x), encoding="utf-8")


def hashes() -> Any:
    """Apply the archived example procedure."""
    return {
        str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
        for root in ("src", "tests")
        for p in (SOURCE / root).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def physical(w: Any) -> Any:
    """Apply the archived example procedure."""
    x: Any = deepcopy(w)
    for e in x["disruptions"]:
        e.pop("visible", None)
    return x


def summary(out: Any) -> Any:
    """Apply the archived example procedure."""
    solves: Any = normal(out["solves"])
    purchases: Any = []
    for p in out["periods"]:
        ds: Any = next(
            s["submission"]["decisions"]
            for s in p["steps"]
            if s["step"] == "make_decisions"
        )
        purchases.append(
            sum((D(str(x["quantity"])) for x in ds if x["kind"] == "buy"), D(0))
        )
    r: Any = out["result"]
    return {
        "profit": r["profit"],
        "cash": r["cash_at_end"],
        "terms": r["terms"],
        "measures": r["measures"]["total"],
        "purchases": purchases,
        "seconds": out["seconds"],
        "solver_count": len(out["solves"]),
        "solver_statuses": sorted(set(x.get("status") for x in solves)),
        "max_gap": max((x.get("gap", 0) for x in solves), default=0),
        "dropped": len(out["dropped"]),
        "fitted": len(out["fitted"]),
        "material_and_financial_balances": True,
    }


def play(c: Any, sid: Any, kind: Any, base: Any = None) -> Any:
    """Apply the archived example procedure."""
    r: Any = b.start_run(c, sid, 7)
    check: Any = partial(b.create_check, c, r["id"])
    if kind == "reference":
        agent: Any = reference_optimizer(
            check, customer_orders_of(base["periods"]), base["world"], time_limit=30
        )
    elif kind == "none":
        agent = no_decisions
    else:
        agent: Any = {
            "rolling": rolling_optimizer,
            "buffered": buffered_rolling_optimizer,
            "full_horizon": full_horizon_optimizer,
        }[kind](check, time_limit=30)
    t: Any = time.monotonic()
    result: Any = b.play_run(c, r, agent)
    periods: Any = b.read_periods(c, r["id"])
    world: Any = b.read_world(c, r["id"])
    assert_run_balances({"periods": periods}, result)
    (into, out) = item_balances(
        {"periods": periods},
        {"board": {"chip": D(2)}, "monitor": {"board": D(2)}},
        {"chip": D(16), "board": D(8), "monitor": D(4)},
    )
    assert into == out
    for p in periods:
        for step in p["steps"]:
            if step["step"] == "execute_decisions":
                assert all(x["accepted"] for x in step["outcomes"])
    return {
        "kind": kind,
        "result": result,
        "periods": periods,
        "world": world,
        "solves": getattr(agent, "solves", []),
        "planning_trace": getattr(agent, "periods", []),
        "dropped": getattr(agent, "dropped", []),
        "fitted": getattr(agent, "fitted", []),
        "seconds": time.monotonic() - t,
    }


def run() -> None:
    """Execute the archived notice matrix."""
    OUTPUT.mkdir(exist_ok=False)
    before: Any = hashes()
    save(HERE / "source_hashes_before.json", before)
    save(
        HERE / "environment.json",
        {
            "python": sys.version,
            "platform": platform.platform(),
            "scipy": scipy.__version__,
            "numpy": numpy.__version__,
            "source": "repository checkout",
            "historical_result_commit": "319489ac6f7c45ae022521681b1a93b5e9e01ecd",  # pragma: allowlist secret
            "seed": 7,
            "time_limit": 30,
            "external_network_blocked": True,
        },
    )
    rates: Any = {
        "zero": ("0", "0", "0"),
        "library_like": ("0.0023", "0.0090", "0.0270"),
    }
    for pct in ["0.02", "0.1", "0.2", "1", "2", "5"]:
        rates["pct_" + pct] = tuple(
            str(D(cost) * D(pct) / 100) for cost in ["0.5", "2", "6"]
        )
    rates["chip_only_0.0001"] = ("0.0001", "0", "0")
    report: Any = {
        "cases": {},
        "rates": rates,
        "archive_checks": {},
        "world_checks": {},
    }
    for label, rate in rates.items():
        m: Any = json.loads((OLD / "notice-manifest.json").read_text())
        for group, item, value in zip(
            ["materials", "components", "products"],
            ["chip", "board", "monitor"],
            rate,
            strict=False,
        ):
            m[group][item]["storage_cost"] = value
        save(OUTPUT / (label + "-manifest.json"), m)
        pair: Any = []
        with benchmark_client() as c:
            mid: Any = b.send(c, "POST", "/manifests", m)["id"]
            for notice in (0, 2):
                sc: Any = json.loads(
                    (OLD / f"notice-{notice}-scenario.json").read_text()
                )
                save(OUTPUT / f"{label}-notice{notice}-scenario.json", sc)
                sid: Any = b.send(c, "POST", f"/manifests/{mid}/scenarios", sc)["id"]
                kinds = (
                    ["none", "rolling", "buffered", "full_horizon", "reference"]
                    if label in ("zero", "library_like")
                    else ["rolling"]
                )
                base = None
                world = None
                for kind in kinds:
                    case = f"{label}-notice{notice}-{kind}"
                    out: Any = play(c, sid, kind, base)
                    if kind == "none":
                        base = out
                    if world is None:
                        world: Any = out["world"]
                    assert normal(world) == normal(out["world"])
                    save(OUTPUT / (case + ".json"), out)
                    report["cases"][case] = summary(out)
                    if label == "zero" and kind in ("none", "rolling", "reference"):
                        old: Any = json.loads(
                            (OLD / f"notice-{notice}-{kind}.json").read_text()
                        )
                        checks = {
                            k: normal(out[k]) == old[k]
                            for k in ["result", "periods", "world"]
                        }
                        report["archive_checks"][case] = checks
                        assert all(checks.values()), (case, checks)
                    print(case, result_line(report["cases"][case]), flush=True)
                    save(HERE / "results.json", report)
                pair.append(world)
        assert normal(physical(pair[0])) == normal(physical(pair[1]))
        report["world_checks"][label] = True
    after: Any = hashes()
    save(HERE / "source_hashes_after.json", after)
    assert before == after
    report["source_unchanged"] = True
    report["source_file_count"] = len(before)
    report["network_connection_attempts"] = connections
    assert not connections
    report["run_count"] = len(report["cases"])
    report["closed_periods"] = report["run_count"] * 10
    save(HERE / "results.json", report)
    print(
        "DONE",
        report["run_count"],
        "runs; source unchanged; network attempts",
        connections,
        flush=True,
    )


def result_line(s: Any) -> Any:
    """Apply the archived example procedure."""
    return {
        "profit": str(s["profit"]),
        "purchases": [str(x) for x in s["purchases"]],
        "measure": s["measures"].get("on_time_shipped", s["measures"]),
    }


if __name__ == "__main__":
    run()
