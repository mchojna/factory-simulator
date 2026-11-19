from decimal import Decimal

import pytest
from factories import benchmark_client
from stress.scale import ScaleProtocol, play_scale_world, scale_lines

from factory_simulator.benchmark import client as benchmark

ONE_PRODUCT_COUNTS = {
    "materials": 4,
    "components": 4,
    "products": 1,
    "suppliers": 1,
    "customers": 1,
    "lines": 1,
}


# The factory generated from seed 2 with 4 materials, 4 components and 1 product,
# from cash 0 and no stock over 10 periods: its product costs at least 213.1738 a unit
# and a unit served is worth at most 179.6824, so the reference makes nothing and earns
# what no decisions earns. The world keeps its row, its profile and both profits, and
# has no score.
@pytest.mark.slow
def test_the_one_product_world_is_unproductive_and_listed_with_equal_profits():
    protocol = ScaleProtocol(
        patterns={"one-product": ONE_PRODUCT_COUNTS},
        economy="unrestricted",
        generator_seeds=range(2, 3),
        run_seeds=range(1),
        scenario={"horizon": 10, "start": {"cash": "0", "stock": {}}},
        agents=("no_decisions", "reference", "rolling_optimizer"),
    )
    with benchmark_client() as client:
        row = play_scale_world(client, protocol, "one-product", 2, 0, 60.0)
        again = benchmark.send(
            client,
            "POST",
            "/manifests/generated",
            {"counts": ONE_PRODUCT_COUNTS, "seed": 2},
        )

    assert row.description == (
        "Generated from 4 materials, 4 components, 1 products, 1 suppliers, "
        "1 customers, 1 lines with seed 2."
    )
    assert again["id"] == row.manifest_id
    assert (row.economic_class, row.useful_demand_coverage) == (
        "unproductive",
        Decimal("0.0000"),
    )
    assert row.no_decisions_profit == row.reference_profit == Decimal("-16915.8353065")
    assert row.denominator == 0
    assert row.scores == {"rolling_optimizer": None}
    assert row.violations == ()
    # 9 items; recipes of 1 + 4 + 3 + 4 and 2 inputs; 4 catalogue entries.
    assert scale_lines([row], protocol.agents)[4] == (
        "| one-product | 2 | 0 | 9 | 14 | 4 | 1 | 1 | unproductive | 0.0000 | -0.5968 "
        "| -16915.8353065 | -16915.8353065 | 0.0000000 | - |"
    )
