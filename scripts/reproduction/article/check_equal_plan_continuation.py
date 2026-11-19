"""Follow the alternative equal-value period-2 action with the same rolling policy."""

from typing import Any

from .diagnose_plans import TOL, input_of, solve_case
from .run_audit import (
    HERE,
    OLD,
    OUTPUT,
    D,
    assert_run_balances,
    b,
    benchmark_client,
    connections,
    deepcopy,
    hashes,
    item_balances,
    json,
    normal,
    partial,
    rolling_optimizer,
    save,
)


def main() -> None:
    """Reproduce this archived example."""
    before: Any = hashes()
    (planning, _trace) = input_of("zero-notice0-rolling", 2)
    alt: Any = solve_case(planning, 16, "1.01", True)
    original: Any = solve_case(planning, 80, "1.01", True)
    assert abs(alt["objective"] - original["objective"]) <= TOL

    def current_nonbuy(sol: Any) -> Any:
        """Apply the archived example procedure."""
        return sorted(
            [
                (tuple(v["key"]), round(v["value"], 8))
                for v in sol["variables"]
                if (v["key"][0] == "make" and v["key"][-1] == 2)
                or (v["key"][0] == "ship" and v["key"][-1] == 2)
            ]
        )

    assert current_nonbuy(alt) == current_nonbuy(original)
    with benchmark_client() as c:
        m: Any = json.loads((OLD / "notice-manifest.json").read_text())
        sc: Any = json.loads((OLD / "notice-0-scenario.json").read_text())
        mid: Any = b.send(c, "POST", "/manifests", m)["id"]
        sid: Any = b.send(c, "POST", f"/manifests/{mid}/scenarios", sc)["id"]
        r: Any = b.start_run(c, sid, 7)
        check: Any = partial(b.create_check, c, r["id"])
        agent: Any = rolling_optimizer(check, time_limit=30)
        edits: Any = []

        def policy(d: Any, o: Any) -> Any:
            """Apply the archived example procedure."""
            a: Any = agent(d, o)
            if o["period"] == 2:
                a: Any = deepcopy(a)
                for x in a:
                    if x["kind"] == "buy" and x["material"] == "chip":
                        assert D(x["quantity"]) == D(80)
                        edits.append(
                            {"period": 2, "old": str(x["quantity"]), "new": "16"}
                        )
                        x["quantity"] = D(16)
                assert all(x["accepted"] for x in check(2, a))
            return a

        result: Any = b.play_run(c, r, policy)
        periods: Any = b.read_periods(c, r["id"])
        world: Any = b.read_world(c, r["id"])
        assert_run_balances({"periods": periods}, result)
        (into, out) = item_balances(
            {"periods": periods},
            {"board": {"chip": D(2)}, "monitor": {"board": D(2)}},
            {"chip": D(16), "board": D(8), "monitor": D(4)},
        )
        assert into == out
        base: Any = json.loads((OUTPUT / "zero-notice0-rolling.json").read_text())
        assert normal(world) == base["world"]
        assert normal(periods[0]) == base["periods"][0]
        assert len(edits) == 1
        evidence: Any = {
            "result": result,
            "periods": periods,
            "world": world,
            "solves": agent.solves,
            "single_intervention": edits,
            "equal_planning_objective": alt["objective"],
            "same_nonbuy_current_decisions": True,
            "same_period_one": True,
            "same_world": True,
            "balances_passed": True,
            "original_profit": base["result"]["profit"],
            "original_on_time": base["result"]["measures"]["total"][
                "units_shipped_on_time"
            ],
        }
        assert before == hashes()
        evidence["source_unchanged"] = True
        evidence["network_attempts"] = connections
        assert not connections
        save(HERE / "equal_plan_continuation.json", evidence)
        print(
            "Alternative equal-valued first action:",
            result["profit"],
            result["measures"]["total"]["units_shipped_on_time"],
            flush=True,
        )


if __name__ == "__main__":
    main()
