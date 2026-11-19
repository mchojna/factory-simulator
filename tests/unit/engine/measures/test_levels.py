from decimal import Decimal

from factories import (
    buy,
    closed_period,
    draw_world_of_bodies,
    produce,
    repair,
    ship,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.engine import compute_profit


def test_profit_so_far_of_the_last_period_leaves_out_the_salvage_of_the_stock():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = 3
    manifest["lines"]["line-1"]["repair_cost"] = "5.0000"
    world = draw_world_of_bodies(manifest, tiny_scenario())
    decisions = {
        1: [
            ship("order-1-1", "4.000"),
            produce("board", "20"),
            buy("50.000"),
            repair("0.0100"),
        ],
        2: [produce("monitor", "4"), ship("order-2-1", "1.000")],
        3: [ship("order-3-1", "4.000")],
        4: [buy("30.000")],
    }

    last = closed_period(world, 5, decisions)

    # Cash 1064.0167 less the starting 1000, plus the receivable 200 of ship-3-1.
    assert last.finished
    assert last.measures["profit_so_far"]["total"] == Decimal("264.0167")
    # The profit adds 20 boards at 0.5000 and 110 chips at 0.1000: 21.
    assert compute_profit(last, world) == Decimal("285.0167")
