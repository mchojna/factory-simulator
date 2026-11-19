import re
from decimal import Decimal
from pathlib import Path

import pytest
from factories import api_client, get, post, run_to_the_end

ROOT = Path(__file__).parents[3]
EXAMPLE_FACTORY = "Electronics factory with economies of scale"
# The sentence of each text that gives the profit of `steady-market`, seed 7, with no
# decisions.
DOCUMENTED_PROFITS = {
    "README.md": r"The program prints `(-?[\d.]+)`",
    "docs/start/quick-start.md": r"It prints `(-?[\d.]+)`",
    "docs/benchmark/playing-a-run.md": (r"against `(-?[\d.]+)` for no decisions"),
    "docs/rules/cash-and-profit.md": (r"no decisions has a profit of (-?[\d.]+)\."),
}


def documented_profit(path: str) -> Decimal:
    found = re.search(DOCUMENTED_PROFITS[path], (ROOT / path).read_text())
    assert found, path
    return Decimal(found[1])


@pytest.mark.slow
def test_the_documented_profit_of_the_quick_start_run_is_the_profit_of_the_run():
    with api_client(load_examples=True) as client:
        _, listed = get(client, "/manifests")
        [factory] = [
            manifest
            for manifest in listed["manifests"]
            if manifest["name"] == EXAMPLE_FACTORY
        ]
        _, scenarios = get(client, f"/manifests/{factory['id']}/scenarios")
        [steady] = [
            scenario
            for scenario in scenarios["scenarios"]
            if scenario["name"] == "steady-market"
        ]
        _, run = post(client, "/runs", {"scenario_id": steady["id"], "seed": 7})
        run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")

    assert result["profit"] == Decimal("-709331.2306")
    for path in DOCUMENTED_PROFITS:
        assert documented_profit(path) == result["profit"], path
