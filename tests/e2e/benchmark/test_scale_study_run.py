import pytest
from factories import benchmark_client
from stress.scale import (
    SCALE_UNSCORABLE_RULE,
    ScaleProtocol,
    play_scale_study,
    scale_lines,
)

from factory_simulator.benchmark import client as benchmark

KINDS = ("materials", "components", "products", "suppliers", "customers", "lines")
PATTERNS: dict[str, dict[str, int]] = {
    "smallest": dict.fromkeys(KINDS, 1),
    "larger": dict(zip(KINDS, (4, 4, 2, 2, 2, 2), strict=True)),
}


def protocol_of(economy: str) -> ScaleProtocol:
    return ScaleProtocol(
        patterns=PATTERNS,
        economy=economy,
        generator_seeds=range(2),
        run_seeds=range(1),
        scenario={"horizon": 8, "start": {"cash": "0", "stock": {}}},
        agents=("no_decisions", "reference", "rolling_optimizer"),
    )


# Two patterns of counts in the matched economy, two generator seeds each, 8 periods
# from cash 0 and no stock. Each row gives the size of the graph and the economic
# profile beside the profits and the score; the rule of unscorable worlds stands above
# the table, and a study in the unrestricted economy is refused before it generates a
# manifest.
@pytest.mark.slow
def test_a_matched_scale_study_records_graph_size_and_profile_beside_scores():
    with benchmark_client() as client:
        with pytest.raises(ValueError, match="plays the matched economy"):
            play_scale_study(client, protocol_of("unrestricted"), 60.0)
        stored = benchmark.read(client, "/manifests")["manifests"]
        rows = play_scale_study(client, protocol_of("matched"), 60.0)
    lines = scale_lines(rows, protocol_of("matched").agents)

    assert stored == []
    assert lines[0] == SCALE_UNSCORABLE_RULE
    assert [(row.pattern, row.generator_seed) for row in rows] == [
        ("smallest", 0),
        ("smallest", 1),
        ("larger", 0),
        ("larger", 1),
    ]
    for row in rows:
        counts = PATTERNS[row.pattern]
        made = counts["components"] + counts["products"]
        assert row.description.endswith(
            f"with seed {row.generator_seed} and matched prices."
        )
        assert row.items == counts["materials"] + made
        assert made <= row.recipe_inputs <= 4 * made
        entries = 2 * counts["materials"] + counts["suppliers"]
        assert counts["materials"] <= row.catalogue_entries <= entries
        assert max(counts["products"], counts["customers"]) <= row.customer_products
        assert row.lines == counts["lines"]
        assert (row.economic_class, str(row.useful_demand_coverage)) == (
            "profitable",
            "1.0000",
        )
        assert row.denominator > 0
        assert row.scores["rolling_optimizer"] is not None
        assert row.violations == ()
    assert lines[-3:-2] == ["| --- | --- | --- | --- |"]
    assert [line.split(" | ")[:3] for line in lines[-2:]] == [
        ["| smallest", "2", "0"],
        ["| larger", "2", "0"],
    ]
