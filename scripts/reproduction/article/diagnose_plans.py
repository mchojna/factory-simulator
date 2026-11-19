"""Reconstruct recorded planning problems and diagnose timing and terminal values.

No engine runs; no changes to source files. Source solver preserves binary variables.
"""

import re
from collections import defaultdict
from dataclasses import replace
from typing import Any, cast

from factory_simulator.benchmark.program import solve as s
from factory_simulator.benchmark.program.expected_source import expected_planning_source

from .run_audit import HERE, OUTPUT, D, connections, hashes, json, normal, save

TOL = 1e-07


def decimals(x: Any) -> Any:
    """Apply the archived example procedure."""
    if isinstance(x, str) and re.fullmatch("-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?", x):
        return D(x)
    if isinstance(x, list):
        return [decimals(v) for v in cast(list[Any], x)]
    if isinstance(x, dict):
        return {k: decimals(v) for (k, v) in cast(dict[str, Any], x).items()}
    return x


def input_of(case: Any, period: Any) -> Any:
    """Apply the archived example procedure."""
    rec: Any = json.loads((OUTPUT / (case + ".json")).read_text())
    t: Any = next(p for p in rec["planning_trace"] if p["period"] == period)
    p: Any = expected_planning_source("lead_chain", "expected", D("1.01"))(
        decimals(t["description"]), decimals(t["observation"])
    )
    assert normal(p) == t["planning_input"], (
        "Reconstructed planning input differs from callback"
    )
    return (p, t)


def solve_case(
    p: Any, first_buy: Any = None, factor: Any = None, strict: Any = False
) -> Any:
    """Apply the archived example procedure."""
    if factor is not None:
        p = replace(
            p,
            terminal_values={
                k: replace(t, value=t.value / D("1.01") * D(factor))
                for (k, t) in p.terminal_values.items()
            },
        )
    program: Any = s.build_program(p, with_rounding=False, exact=False)
    buyvars = {
        i: 1.0
        for (k, i) in program.variables.items()
        if k[0] == "buy" and k[2] == "chip" and (k[3] == p.first_period)
    }
    assert buyvars
    if first_buy is not None:
        program.add_equal(s.Expression(terms=buyvars), float(first_buy))
    unit: Any = s.build_money_unit(program, p.first_period)
    assert unit == 1.0
    oldgap = s.GAP_LIMIT
    if strict:
        s.GAP_LIMIT = 1e-09
    try:
        if program.binaries:
            (values, value, report) = s.solve_integer(program, 30, p.first_period)
        else:
            (values, value, report) = s._solve_with_diagnostics(program, time_limit=30)  # pyright: ignore[reportPrivateUsage]
    finally:
        s.GAP_LIMIT = oldgap
    assert values is not None and value is not None
    values = cast(Any, values)
    assert report.status == 0
    gap: Any = getattr(report, "gap", 0)
    assert gap <= TOL
    atmost: Any = max(
        [0.0]
        + [
            sum(coef * values[i] for (i, coef) in terms.items()) - bound
            for (terms, bound) in program.at_most_rows
        ]
    )
    eq: Any = max(
        [0.0]
        + [
            abs(sum(coef * values[i] for (i, coef) in terms.items()) - bound)
            for (terms, bound) in program.equal_rows
        ]
    )
    integ: Any = max(
        [0.0] + [abs(values[i] - round(values[i])) for i in program.binaries]
    )
    assert max(atmost, eq, integ) <= TOL
    components: Any = defaultdict[str, float](float)
    components["constant"] = program.objective.constant
    for key, i in program.variables.items():
        components[str(key[0])] += program.objective.terms.get(i, 0) * values[i]
    assert abs(sum(components.values()) - value) <= TOL
    selected = [
        {"key": list(k), "value": float(values[i])}
        for (k, i) in program.variables.items()
        if abs(values[i]) > 1e-08
        and k[0]
        in ("buy", "make", "ship", "terminal_cost", "terminal_salvage", "stock")
    ]
    return {
        "objective": value,
        "first_buy": sum(values[i] for i in buyvars),
        "factor": factor or "1.01",
        "strict": strict,
        "report": report,
        "objective_components": dict(components),
        "variables": selected,
        "binary_count": len(program.binaries),
        "max_constraint_residual": max(atmost, eq),
        "max_integrality_residual": integ,
    }


def main() -> None:
    """Reproduce this archived example."""
    before: Any = hashes()
    res: Any = {
        "objective_comparison_tolerance": TOL,
        "strict_absolute_mip_gap": 1e-09,
        "source_relative_gap": 0,
        "questions": {},
    }
    for case, period, choices in [
        ("zero-notice0-rolling", 2, [16, 80]),
        ("chip_only_0.0001-notice0-rolling", 2, [16, 80]),
        ("library_like-notice0-rolling", 2, [16, 80]),
        ("zero-notice2-rolling", 1, [16, 128]),
        ("library_like-notice2-rolling", 2, [32, 176]),
        ("pct_0.2-notice2-rolling", 2, [32, 176]),
    ]:
        (p, t) = input_of(case, period)
        q: Any = {
            "case": case,
            "period": period,
            "window_end": p.window_end,
            "terminal_values": p.terminal_values,
            "input_reconstructed_exactly": True,
        }
        original: Any = solve_case(p)
        recorded: Any = next(z for z in t["solves"] if z.get("value") is not None)
        submitted: Any = sum(
            float(z["quantity"])
            for z in t["decisions"]
            if z["kind"] == "buy" and z["material"] == "chip"
        )
        assert abs(original["objective"] - recorded["value"]) <= TOL
        assert abs(original["first_buy"] - submitted) <= TOL
        q["original_callback_reproduced"] = True
        q["original"] = original
        q["variants"] = {}
        for factor in ["1.01", "1.00"]:
            for buy in [None, *choices]:
                tag = f"factor{factor}-buy{buy}"
                q["variants"][tag] = solve_case(p, buy, factor, True)
        res["questions"][case + "-period" + str(period)] = q
        save(HERE / "diagnostics.json", res)
        print(case, "period", period, "window_end", p.window_end, flush=True)
        for k, v in q["variants"].items():
            print(k, v["objective"], v["first_buy"], flush=True)
    assert before == hashes()
    res["source_unchanged"] = True
    res["network_attempts"] = connections
    assert not connections
    save(HERE / "diagnostics.json", res)
    print("DIAGNOSTIC CHECKS COMPLETE", flush=True)


if __name__ == "__main__":
    main()
