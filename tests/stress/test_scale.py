from dataclasses import replace
from decimal import Decimal

import pytest

from stress.scale import (
    SCALE_UNSCORABLE_RULE,
    ScaleProtocol,
    ScaleRow,
    check_scale_protocol,
    scale_lines,
)

PROTOCOL = ScaleProtocol(
    patterns={"small": {"materials": 1}, "large": {"materials": 8}},
    economy="matched",
    generator_seeds=range(1),
    run_seeds=range(2),
    scenario={"horizon": 8},
    agents=("no_decisions", "reference", "rolling_optimizer", "myopic_optimizer"),
)
ROW = ScaleRow(
    pattern="small",
    generator_seed=0,
    seed=0,
    manifest_id="m",
    description="d",
    items=3,
    recipe_inputs=2,
    catalogue_entries=1,
    customer_products=1,
    lines=1,
    economic_class="profitable",
    useful_demand_coverage=Decimal("1.0000"),
    margin_share=Decimal("0.4262"),
    no_decisions_profit=Decimal("-100"),
    reference_profit=Decimal("300"),
    denominator=Decimal("400"),
    scores={"rolling_optimizer": Decimal("0.5"), "myopic_optimizer": Decimal("0.75")},
    violations=(),
)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"economy": "unrestricted"},
            "a scale study plays the matched economy, not unrestricted",
        ),
        (
            {"patterns": {"small": {"materials": 1}}},
            "a scale study compares at least two patterns of counts",
        ),
        (
            {"agents": ("reference", "no_decisions", "rolling_optimizer")},
            "a scale study plays no decisions and the reference first",
        ),
    ],
)
def test_a_protocol_outside_a_matched_comparison_is_refused(
    changes: dict[str, object], message: str
):
    with pytest.raises(ValueError) as refused:
        check_scale_protocol(replace(PROTOCOL, **changes))

    assert str(refused.value) == message


def test_a_matched_protocol_of_two_patterns_passes():
    check_scale_protocol(PROTOCOL)


# Two worlds of small with best scores 0.75 and 0.25 average 0.5; the unscorable world
# of large keeps its row and its profits, counts in its pattern and has no mean.
def test_an_unscorable_world_keeps_its_row_and_counts_in_its_pattern():
    second = replace(
        ROW,
        seed=1,
        scores={"rolling_optimizer": Decimal("0.25"), "myopic_optimizer": None},
    )
    unscorable = replace(
        ROW,
        pattern="large",
        reference_profit=Decimal("-100"),
        denominator=Decimal("0"),
        scores={"rolling_optimizer": None, "myopic_optimizer": None},
    )

    lines = scale_lines([ROW, second, unscorable], PROTOCOL.agents)

    assert lines[0] == SCALE_UNSCORABLE_RULE
    assert lines[6] == (
        "| large | 0 | 0 | 3 | 2 | 1 | 1 | 1 | profitable | 1.0000 | 0.4262 | -100 "
        "| -100 | 0 | - | - |"
    )
    assert lines[-2:] == ["| small | 2 | 0 | 0.500 |", "| large | 1 | 1 | - |"]
