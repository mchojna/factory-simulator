"""Twelve preregistered offline runs; all outcomes are retained."""

from typing import Any

from .run_audit import (
    HERE,
    OLD,
    OUTPUT,
    D,
    b,
    benchmark_client,
    connections,
    hashes,
    json,
    normal,
    play,
    result_line,
    save,
    summary,
)


def main() -> None:
    """Reproduce this archived example."""
    target = HERE / "extension-records"
    target.mkdir(exist_ok=False)
    before: Any = hashes()
    report: Any = {
        "cases": {},
        "rates_percent": ["0.02", "0.1", "0.2", "1", "2", "5"],
        "seed": 7,
        "horizon": 10,
        "notice": 2,
        "time_limit": 30,
        "expected_service_not_used_as_pass_criterion": True,
    }
    for pct in report["rates_percent"]:
        label = "pct_" + pct
        m: Any = json.loads((OLD / "notice-manifest.json").read_text())
        for group, item, cost in zip(
            ["materials", "components", "products"],
            ["chip", "board", "monitor"],
            ["0.5", "2", "6"],
            strict=False,
        ):
            m[group][item]["storage_cost"] = str(D(cost) * D(pct) / 100)
        sc: Any = json.loads((OLD / "notice-2-scenario.json").read_text())
        save(target / (label + "-manifest.json"), m)
        save(target / (label + "-scenario.json"), sc)
        with benchmark_client() as c:
            mid: Any = b.send(c, "POST", "/manifests", m)["id"]
            sid: Any = b.send(c, "POST", f"/manifests/{mid}/scenarios", sc)["id"]
            world = None
            for kind in ["buffered", "full_horizon"]:
                case = f"{label}-notice2-{kind}"
                out: Any = play(c, sid, kind)
                assert len(out["periods"]) == 10
                if world is None:
                    world: Any = out["world"]
                assert normal(world) == normal(out["world"])
                rolling: Any = json.loads(
                    (OUTPUT / (label + "-notice2-rolling.json")).read_text()
                )
                assert normal(world) == rolling["world"]
                save(target / (case + ".json"), out)
                report["cases"][case] = summary(out)
                print(case, result_line(report["cases"][case]), flush=True)
                save(HERE / "extension-results.json", report)
    assert hashes() == before
    assert not connections
    report.update(
        source_unchanged=True,
        network_attempts=connections,
        run_count=len(report["cases"]),
        closed_periods=120,
    )
    save(HERE / "extension-results.json", report)
    print("TWELVE RUNS COMPLETE", flush=True)


if __name__ == "__main__":
    main()
