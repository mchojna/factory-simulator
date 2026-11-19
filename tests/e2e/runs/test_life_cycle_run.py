from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    assert_run_balances,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 52


def life_cycle_factor(period: int) -> Decimal:
    s_curve = 1 / (1 + (-Decimal("0.5000") * (period - 10)).exp())
    trend = Decimal("1.0050") ** (period - 1)
    step = 0 if period >= 45 else 1
    return s_curve * trend * step


# The units ordered in each period of a run, which balances.
def run_of(manifest: dict[str, Any], scenario: dict[str, Any]) -> list[Decimal]:
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=2)
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    assert_run_balances(periods, result)
    return [
        period["steps"][-1]["measures"]["total"]["units_ordered"]
        for period in periods["periods"]
    ]


@pytest.mark.slow
def test_a_product_life_cycle_rises_grows_and_ends():
    manifest = tiny_manifest()
    customer_product = manifest["customers"]["distributor"]["products"]["monitor"]
    customer_product["demand"] = {"min": "35.000", "max": "45.000"}
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    # Without persistence and shapes, the units ordered are the drawn demand.
    drawn = run_of(manifest, scenario)
    customer_product["demand_persistence"] = "0.5000"
    scenario["demand_shapes"] = [
        {
            "kind": "s_curve",
            "target": "all",
            "middle": 10,
            "steepness": "0.5000",
            "from_factor": "0.0000",
            "to_factor": "1.0000",
        },
        {"kind": "trend", "target": "all", "rate": "0.0050"},
        {"kind": "step", "target": "all", "period": 45, "factor": "0.0000"},
    ]
    ordered = run_of(manifest, scenario)

    # base(1) = draw(1) and base(t) = 0.5 * base(t - 1) + 0.5 * draw(t).
    bases = [drawn[0]]
    for draw in drawn[1:]:
        bases.append((bases[-1] / 2 + draw / 2).quantize(Decimal("0.001")))
    expected = [
        (base * life_cycle_factor(period)).quantize(Decimal("0.001"))
        for period, base in enumerate(bases, start=1)
    ]
    assert ordered == expected
