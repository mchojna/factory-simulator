"""Reproduce the archived article evidence with the current repository."""

from typing import Any


def main() -> None:
    """Reproduce this archived example."""
    import json
    import time
    from copy import deepcopy
    from dataclasses import asdict, is_dataclass
    from decimal import Decimal as D
    from functools import partial

    from factories import assert_run_balances, benchmark_client, plain_tiny_manifest

    from factory_simulator.benchmark import client as b
    from factory_simulator.benchmark.optimizers.no_decisions import no_decisions
    from factory_simulator.benchmark.optimizers.reference import (
        customer_orders_of,
        reference_optimizer,
    )
    from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer

    from .context import OUTPUT as WORK

    ROOT = WORK / "examples" / "reference"
    ROOT.mkdir(parents=True, exist_ok=False)

    def dump(x: Any) -> Any:
        """Apply the archived example procedure."""
        return json.dumps(
            x,
            default=lambda v: (
                asdict(v) if is_dataclass(v) and (not isinstance(v, type)) else str(v)
            ),
            indent=2,
            sort_keys=True,
        )

    def save(n: Any, x: Any) -> None:
        """Write the evidence as JSON."""
        (ROOT / (n + ".json")).write_text(dump(x))

    def setup(c: Any, m: Any, s: Any) -> Any:
        """Apply the archived example procedure."""
        mid: Any = b.send(c, "POST", "/manifests", m)["id"]
        return b.send(c, "POST", f"/manifests/{mid}/scenarios", s)["id"]

    def play(
        c: Any, sid: Any, agent_kind: Any, base: Any = None, policy: Any = None
    ) -> Any:
        """Apply the archived example procedure."""
        r: Any = b.start_run(c, sid, 7)
        check: Any = partial(b.create_check, c, r["id"])
        if agent_kind in ["reference", "exact"]:
            agent: Any = reference_optimizer(
                check,
                customer_orders_of(base["periods"]),
                base["world"],
                time_limit=30,
                exact=agent_kind == "exact",
            )
        elif agent_kind == "rolling":
            agent: Any = rolling_optimizer(check, time_limit=30)
        elif agent_kind == "rule":
            agent = policy
        else:
            agent = no_decisions
        begin: Any = time.monotonic()
        result: Any = b.play_run(c, r, agent)
        elapsed = time.monotonic() - begin
        periods: Any = b.read_periods(c, r["id"])
        world: Any = b.read_world(c, r["id"])
        assert_run_balances({"periods": periods}, result)
        out: Any = {
            "agent": agent_kind,
            "result": result,
            "periods": periods,
            "world": world,
            "seconds": elapsed,
            "solves": getattr(agent, "solves", []),
            "dropped": getattr(agent, "dropped", []),
            "fitted": getattr(agent, "fitted", []),
        }
        return out

    report: Any = {"micro": {}}
    with benchmark_client() as c:
        m: Any = plain_tiny_manifest()
        m["name"] = "Allocation optimum micro-instance"
        for k in ["materials", "components", "products"]:
            for x in m[k].values():
                x["salvage_value"] = "0"
        terms: Any = m["customers"]["distributor"]["products"]["monitor"]
        terms.update(demand="0", patience=0)
        m["customers"]["premium"] = deepcopy(m["customers"]["distributor"])
        m["customers"]["premium"]["products"]["monitor"]["price"] = "70"
        s: Any = {
            "name": "Single allocation",
            "horizon": 1,
            "start": {
                "cash": "0",
                "stock": {
                    "main": {"chip": "0.001", "board": "0.001", "monitor": "0.001"}
                },
                "customer_orders": [
                    {
                        "customer": cust,
                        "product": "monitor",
                        "quantity": "0.001",
                        "due": 1,
                    }
                    for cust in ["distributor", "premium"]
                ],
            },
        }
        save("micro-manifest", m)
        save("micro-scenario", s)
        sid: Any = setup(c, m, s)
        base: Any = play(c, sid, "none")
        save("micro-none", base)
        for kind in ["reference", "exact", "rolling"]:
            out: Any = play(c, sid, kind, base)
            save("micro-" + kind, out)
            report["micro"][kind] = {
                "profit": out["result"]["profit"],
                "solves": out["solves"],
            }
        for choice in ["none", "distributor", "premium"]:

            def allocation(_d: Any, o: Any, choice: Any = choice) -> Any:
                """Apply the archived example procedure."""
                return [
                    {"kind": "ship", "order": x["id"], "quantity": "0.001"}
                    for x in o["customer_orders"]
                    if x["customer"] == choice
                ]

            out: Any = play(c, sid, "rule", policy=allocation)
            save("micro-allocation-" + choice, out)
            report["micro"][choice] = {"profit": out["result"]["profit"]}
        report["micro"]["analytical_upper_bound"] = "0.059"
        assert D(report["micro"]["reference"]["profit"]) == D("0.059")
        assert max(
            D(report["micro"][k]["profit"]) for k in ["none", "distributor", "premium"]
        ) == D("0.059")
        save("reference-example-results", report)
        print("MICRO", report["micro"], flush=True)


if __name__ == "__main__":
    main()
