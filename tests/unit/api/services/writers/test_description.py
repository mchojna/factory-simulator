from decimal import Decimal
from typing import Any, cast

import pytest
from factories import example_count
from hypothesis import example, given, settings
from hypothesis import strategies as st

from factory_simulator.api.record.database import canonical_text, read_column
from factory_simulator.api.services.writers.description import add_cut_means

# Bounds as whole numbers or with 3 places, so that many of them read back as ints.
bounds = st.one_of(
    st.integers(min_value=1, max_value=100).map(Decimal),
    st.decimals(min_value=Decimal("0.001"), max_value=100, places=3),
)


# A uniform, triangular, normal or lognormal range of decimals.
@st.composite
def written_ranges(draw: st.DrawFn) -> dict[str, Any]:
    low, high = sorted(draw(st.lists(bounds, min_size=2, max_size=2, unique=True)))
    centre = draw(
        st.one_of(
            st.sampled_from([low, high]), st.decimals(min_value=low, max_value=high)
        )
    )
    centre = centre.quantize(Decimal("0.001")).max(low).min(high)
    width = draw(st.decimals(min_value=Decimal("0.0001"), max_value=10, places=4))
    return draw(
        st.sampled_from(
            [
                {"min": low, "max": high},
                {"min": low, "max": high, "distribution": "triangular", "mode": centre},
                {
                    "min": low,
                    "max": high,
                    "distribution": "normal",
                    "mean": centre,
                    "sd": width,
                },
                {
                    "min": low,
                    "max": high,
                    "distribution": "lognormal",
                    "median": centre,
                    "spread": width,
                },
            ]
        )
    )


def cut_mean(value_range: dict[str, Any]) -> Decimal:
    document = dict(value_range)
    add_cut_means(document)
    return document["cut_mean"]


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(written_ranges())
@example(
    {
        "min": Decimal("0.036"),
        "max": Decimal("1.0000"),
        "distribution": "lognormal",
        "median": Decimal("1.0000"),
        "spread": Decimal("0.0001"),
    }
)
def test_a_range_read_back_from_its_canonical_text_keeps_its_cut_mean(
    value_range: dict[str, Any],
):
    read_back = cast(dict[str, Any], read_column(canonical_text(value_range)))

    assert cut_mean(read_back) == cut_mean(value_range)


def test_a_lognormal_range_of_whole_numbers_has_the_cut_mean_of_its_decimals():
    demand = {"min": 14, "max": 70, "distribution": "lognormal", "median": 35}

    assert cut_mean(demand | {"spread": Decimal("0.4")}) == Decimal("36.222159")


def test_a_triangular_range_of_whole_numbers_has_the_mean_of_its_3_points():
    capacity = {"min": 60, "max": 90, "distribution": "triangular", "mode": 80}

    assert cut_mean(capacity) == Decimal("76.666667")


def test_a_normal_range_with_a_whole_min_has_the_mean_of_its_cut_distribution():
    demand = {"min": 38, "max": 60, "distribution": "normal", "mean": 40, "sd": 5}

    assert cut_mean(demand) == Decimal("42.808528")


def test_a_range_of_periods_keeps_the_middle_of_its_bounds():
    assert cut_mean({"min": 1, "max": 4}) == Decimal("2.5")
