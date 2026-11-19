from decimal import Decimal

import pytest
from factories import (
    api_client,
    database_file,
    get,
    narrow_demand_bodies,
    run_to_the_end,
    start_run,
    submit,
)

from factory_simulator.benchmark.program.expected_source import (
    customer_product_demand,
)


# A run of a normal demand of standard deviation 10**20 from 1 to 9, stopped after
# period 4 and finished after a restart, keeps the world of the same run played without
# a stop, and plans the demand of the customer product at the mean 5 of its flat
# distribution.
@pytest.mark.slow
def test_a_narrow_demand_replays_its_draws_and_plans_at_its_mean_after_a_restart():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client, *narrow_demand_bodies(), seed=0)
            for period in range(1, 5):
                status, _ = submit(client, run["id"], period, [])
                assert status == 200
        with api_client(url) as client:
            _, resumed = get(client, f"/runs/{run['id']}")
            run_to_the_end(client, resumed)
            _, world = get(client, f"/runs/{run['id']}/world")
    with api_client() as client:
        played = start_run(client, *narrow_demand_bodies(), seed=0)
        run_to_the_end(client, played)
        _, unbroken = get(client, f"/runs/{played['id']}/world")

    assert world == unbroken
    assert len(set(world["demand"]["distributor/monitor"])) > 1
    manifest = run["description"]["manifest"]
    customer_product = manifest["customers"]["distributor"]["products"]["monitor"]
    assert customer_product_demand(
        "distributor", "monitor", {}, customer_product
    ) == Decimal(5)
