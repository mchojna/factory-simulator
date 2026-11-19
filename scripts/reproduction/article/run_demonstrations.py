"""Reproduce the archived article evidence with the current repository."""

from typing import Any


def main() -> None:
    """Reproduce the archived fulfilment, fork and disclosure checks."""
    import hashlib
    import importlib.metadata
    import json
    import platform
    from copy import deepcopy
    from decimal import Decimal

    from factories import (
        api_client,
        assert_run_balances,
        engine_of,
        get,
        item_balances,
        plain_tiny_manifest,
        post,
        server_of,
        start_run,
        submit,
    )
    from sqlalchemy.orm import Session

    from factory_simulator.api.record.models.run import Run
    from factory_simulator.api.services.runs.replay import replay_run

    from .context import OUTPUT as WORK

    ROOT = WORK / "examples" / "order-fulfilment"
    ROOT.mkdir(parents=True, exist_ok=False)
    COMMIT = "historical results: 319489ac6f7c45ae022521681b1a93b5e9e01ecd; execution: current repository checkout"

    def dump(x: Any) -> Any:
        """Apply the archived example procedure."""
        return json.dumps(x, default=str, sort_keys=True, indent=2)

    def sha(x: Any) -> Any:
        """Apply the archived example procedure."""
        return hashlib.sha256(dump(x).encode()).hexdigest()

    manifest: Any = plain_tiny_manifest()
    manifest["name"] = "Manuscript two-stage factory"
    manifest["customers"]["distributor"]["products"]["monitor"].update(
        demand="0.000", patience=1
    )
    manifest["customers"]["distributor"]["payment_terms"] = 1
    scenario: Any = {
        "name": "Manuscript five-period order",
        "horizon": 5,
        "start": {
            "cash": "1000",
            "stock": {"main": {"chip": "0", "board": "0", "monitor": "0"}},
            "customer_orders": [
                {
                    "customer": "distributor",
                    "product": "monitor",
                    "quantity": "4",
                    "due": 4,
                }
            ],
        },
    }
    (ROOT / "manifest.json").write_text(dump(manifest))
    (ROOT / "scenario.json").write_text(dump(scenario))

    def controller(_description: Any, obs: Any, assembly_period: Any = 3) -> Any:
        """Apply the archived example procedure."""
        t: Any = obs["period"]
        actions: Any = []
        available: Any = Decimal(obs["stock"]["main"]["monitor"])
        for order in obs["customer_orders"]:
            quantity: Any = min(
                available, Decimal(order["quantity"]) - Decimal(order["shipped"])
            )
            if quantity > 0:
                actions.append(
                    {"kind": "ship", "order": order["id"], "quantity": str(quantity)}
                )
                available -= quantity
        if t == 1:
            actions.append(
                {
                    "kind": "buy",
                    "supplier": "chip-maker",
                    "material": "chip",
                    "quantity": "16",
                }
            )
        if t == 2:
            actions.append(
                {"kind": "produce", "line": "line-1", "item": "board", "quantity": "8"}
            )
        if t == assembly_period:
            actions.append(
                {
                    "kind": "produce",
                    "line": "line-1",
                    "item": "monitor",
                    "quantity": "4",
                }
            )
        return actions

    def play(
        client: Any, run: Any, assembly_period: Any = 3, empty: Any = False
    ) -> Any:
        """Apply the archived example procedure."""
        while True:
            (status, obs) = get(client, f"/runs/{run['id']}/observation")
            assert status == 200, obs
            if obs.get("finished"):
                break
            decisions: Any = (
                [] if empty else controller(run["description"], obs, assembly_period)
            )
            (status, result) = submit(client, run["id"], obs["period"], decisions)
            assert status == 200, result
            if result.get("finished"):
                break
        (_, periods) = get(client, f"/runs/{run['id']}/periods")
        (_, result) = get(client, f"/runs/{run['id']}/result")
        assert_run_balances(periods, result)
        (into, out) = item_balances(
            periods,
            {"board": {"chip": Decimal(2)}, "monitor": {"board": Decimal(2)}},
            {"chip": Decimal(0), "board": Decimal(0), "monitor": Decimal(0)},
        )
        assert into == out
        return (periods, result)

    with api_client() as client:
        parent: Any = start_run(client, manifest, scenario, seed=7)
        (p, r) = play(client, parent)
        again: Any = start_run(client, manifest, scenario, seed=7)
        (p2, r2) = play(client, again)
        assert p == p2 and r == r2
        with Session(engine_of(client), expire_on_commit=False) as session:
            run: Any = session.get(Run, parent["id"])
            (_world, closed, _state) = replay_run(server_of(client), session, run, 4)
            assert len(closed) == 4
        (status, replayed) = post(client, f"/runs/{parent['id']}/forks", {"period": 5})
        assert status == 201
        (replayp, replayr) = play(client, replayed)
        assert replayp == p and replayr == r
        (status, fork) = post(client, f"/runs/{parent['id']}/forks", {"period": 3})
        assert status == 201, fork
        (_, prefix) = get(client, f"/runs/{fork['id']}/periods")
        assert prefix["periods"] == p["periods"][:2]
        (fp, fr) = play(client, fork, assembly_period=4)
        fresh: Any = start_run(client, manifest, scenario, seed=7)
        (freshp, freshr) = play(client, fresh, assembly_period=4)
        assert fp == freshp and fr == freshr
        (_, pw) = get(client, f"/runs/{parent['id']}/world")
        (_, fw) = get(client, f"/runs/{fork['id']}/world")
        assert pw == fw
        base: Any = start_run(client, manifest, scenario, seed=7)
        (bp, br) = play(client, base, empty=True)
        hidden_scenario: Any = deepcopy(scenario)
        hidden_scenario["hidden"] = ["lines.items.yield"]
        hidden: Any = start_run(client, manifest, hidden_scenario, seed=7)
        (_, hw) = get(client, f"/runs/{hidden['id']}/world")
        hidden_item: Any = hidden["description"]["manifest"]["lines"]["line-1"][
            "items"
        ]["board"]
        visible_item: Any = parent["description"]["manifest"]["lines"]["line-1"][
            "items"
        ]["board"]
        assert "yield" in visible_item and "yield" not in hidden_item
        (hp, hr) = play(client, hidden)
        assert hp == p and hr == r
        for name, periods, result in [
            ("parent", p, r),
            ("fork", fp, fr),
            ("baseline", bp, br),
            ("hidden", hp, hr),
        ]:
            (ROOT / f"{name}-periods.json").write_text(dump(periods))
            (ROOT / f"{name}-result.json").write_text(dump(result))
        report: Any = {
            "commit": COMMIT,
            "package_version": importlib.metadata.version("factory-simulator"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": importlib.metadata.version("numpy"),
            "seed": 7,
            "horizon": 5,
            "transport": "HTTP request/response interface through in-process ASGI transport",
            "parent_profit": r["profit"],
            "fork_profit": fr["profit"],
            "baseline_profit": br["profit"],
            "parent_cash": r["cash_at_end"],
            "fork_cash": fr["cash_at_end"],
            "fork_receivables": fr["receivables"],
            "parent_period_sha256": sha(p),
            "repeated_period_sha256": sha(p2),
            "parent_prefix_sha256": sha(p["periods"][:2]),
            "fork_prefix_sha256": sha(prefix["periods"]),
            "replay_verified_periods": len(closed),
            "fork_matches_fresh_alternative": fp == freshp,
            "world_parent_equals_fork": pw == fw,
            "physical_periods_hidden_equal_visible": hp == p,
            "visible_yield": visible_item["yield"],
            "hidden_yield_absent": "yield" not in hidden_item,
            "financial_and_material_balance_runs": 7,
            "replayed_continuation_sha256": sha(replayp),
            "reference_optimizer_used": False,
        }
        (ROOT / "demonstration-results.json").write_text(dump(report))
        (ROOT / "world-visible.json").write_text(dump(pw))
        (ROOT / "world-hidden.json").write_text(dump(hw))
        print(dump(report))


if __name__ == "__main__":
    main()
