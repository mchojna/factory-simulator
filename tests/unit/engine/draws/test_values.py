from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any, cast

import pytest
from factories import (
    FactoryBodies,
    draw_world_of_bodies,
    quantities,
    seeds,
    small_factories,
)
from hypothesis import assume, given
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json
from factory_simulator.engine import (
    CONTEXT,
    Cascade,
    Range,
    carry_demand_over,
    choose_target,
    combine_demand_draws,
    draw_value,
    is_within_chance,
    raised_chances,
    range_mean,
)
from factory_simulator.engine.draws.values import draw_periods

u_values = st.decimals(
    min_value=0, max_value=Decimal("0.9999999999"), places=10, allow_nan=False
)


DELAYS_CHANCE = Decimal("0.1000")


RAISE_DELAYS = Cascade(rule="delays", factor=Decimal("3.0000"), periods=2)


DEMAND = Range(min=Decimal("30.000"), max=Decimal("50.000"))


QUANTILES = ("0.01", "0.25", "0.5", "0.75", "0.99")


uniforms = st.floats(min_value=0, max_value=1).map(
    lambda uniform: Decimal(repr(uniform))
)


common_shares = st.integers(min_value=0, max_value=10000).map(
    lambda number: Decimal(number).scaleb(-4)
)


def triangular(low: str, high: str, mode: str) -> Range[Decimal]:
    return Range(
        min=Decimal(low),
        max=Decimal(high),
        distribution="triangular",
        mode=Decimal(mode),
    )


def normal(low: str, high: str, mean: str, sd: str) -> Range[Decimal]:
    return Range(
        min=Decimal(low),
        max=Decimal(high),
        distribution="normal",
        mean=Decimal(mean),
        sd=Decimal(sd),
    )


def lognormal(low: str, high: str, median: str, spread: str) -> Range[Decimal]:
    return Range(
        min=Decimal(low),
        max=Decimal(high),
        distribution="lognormal",
        median=Decimal(median),
        spread=Decimal(spread),
    )


# An oracle of the cut normal in decimals of 120 digits, independent of floating point.
PI = Decimal(
    "3.14159265358979323846264338327950288419716939937510582097494459230781640628"
    "620899862803482534211706798214808651328230664709384460955058223172535940813"
)


# erf(x) = 2 / sqrt(pi) * exp(-x * x) * sum of 2**n * x**(2n + 1) / (1 * 3 * ... *
# (2n + 1)), whose terms are all positive. Beyond 17 it is 1 to 120 digits.
def oracle_erf(x: Decimal) -> Decimal:
    size = abs(x)
    if size == 0:
        return Decimal(0)
    if size > 17:
        return Decimal(1).copy_sign(x)
    term = total = size
    steps = 0
    while term > total * Decimal("1e-125"):
        steps += 1
        term = term * 2 * size * size / (2 * steps + 1)
        total += term
    return (2 / PI.sqrt() * (-size * size).exp() * total).copy_sign(x)


def oracle_cdf(z: Decimal) -> Decimal:
    return (1 + oracle_erf(z / Decimal(2).sqrt())) / 2


def oracle_pdf(z: Decimal) -> Decimal:
    return (-z * z / 2).exp() / (2 * PI).sqrt()


# The z of the standard normal cut to low to high at u, by 200 bisections.
def oracle_standard_value(low: Decimal, high: Decimal, uniform: Decimal) -> Decimal:
    target = oracle_cdf(low) + uniform * (oracle_cdf(high) - oracle_cdf(low))
    for _ in range(200):
        middle = (low + high) / 2
        if oracle_cdf(middle) < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def in_oracle_context[T](compute: Callable[[], T]) -> T:
    with localcontext() as context:
        context.prec = 120
        return compute()


def oracle_normal_mean(value_range: Range[Decimal]) -> Decimal:
    mean, sd = cast(Decimal, value_range.mean), cast(Decimal, value_range.sd)

    def compute() -> Decimal:
        low, high = (value_range.min - mean) / sd, (value_range.max - mean) / sd
        cut = (oracle_pdf(low) - oracle_pdf(high)) / (
            oracle_cdf(high) - oracle_cdf(low)
        )
        return mean + sd * cut

    return round(in_oracle_context(compute), 6)


def oracle_normal_value(value_range: Range[Decimal], uniform: Decimal) -> Decimal:
    mean, sd = cast(Decimal, value_range.mean), cast(Decimal, value_range.sd)

    def compute() -> Decimal:
        low, high = (value_range.min - mean) / sd, (value_range.max - mean) / sd
        return mean + sd * oracle_standard_value(low, high, uniform)

    return round(in_oracle_context(compute), 3)


def oracle_lognormal_mean(value_range: Range[Decimal]) -> Decimal:
    median, spread = (
        cast(Decimal, value_range.median),
        cast(Decimal, value_range.spread),
    )

    def compute() -> Decimal:
        low = (value_range.min / median).ln() / spread
        high = (value_range.max / median).ln() / spread
        shifted = oracle_cdf(high - spread) - oracle_cdf(low - spread)
        within = oracle_cdf(high) - oracle_cdf(low)
        return median * (spread * spread / 2).exp() * shifted / within

    return round(in_oracle_context(compute), 6)


def oracle_lognormal_value(value_range: Range[Decimal], uniform: Decimal) -> Decimal:
    median, spread = (
        cast(Decimal, value_range.median),
        cast(Decimal, value_range.spread),
    )

    def compute() -> Decimal:
        low = (value_range.min / median).ln() / spread
        high = (value_range.max / median).ln() / spread
        return median * (spread * oracle_standard_value(low, high, uniform)).exp()

    return round(in_oracle_context(compute), 3)


@st.composite
def triangular_ranges(draw: st.DrawFn) -> Range[Decimal]:
    low, high = sorted(
        draw(
            st.lists(
                st.decimals(min_value=0, max_value=1000, places=3),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
    )
    mode = draw(st.decimals(min_value=low, max_value=high, places=3))
    return Range(min=low, max=high, distribution="triangular", mode=mode)


# Standard deviations from 1 to 10**30, under which a range from 0 to 1000 is narrow.
large_sds = st.integers(min_value=0, max_value=30).map(
    lambda power: Decimal(f"{10**power}.000")
)


# Normal ranges with the mean anywhere from min to max and standard deviations from
# 0.001 to 10**30.
@st.composite
def normal_ranges(draw: st.DrawFn) -> Range[Decimal]:
    low, high = sorted(
        draw(
            st.lists(
                st.decimals(min_value=0, max_value=1000, places=3),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
    )
    mean = draw(st.decimals(min_value=low, max_value=high, places=3))
    sd = draw(
        st.one_of(
            st.decimals(min_value=Decimal("0.001"), max_value=1000, places=3), large_sds
        )
    )
    return Range(min=low, max=high, distribution="normal", mean=mean, sd=sd)


# Lognormal ranges with the median anywhere from min to max, at a bound included, and
# spreads from small enough that the other bound lies far in a tail up to 10.
@st.composite
def lognormal_ranges(draw: st.DrawFn) -> Range[Decimal]:
    low, high = sorted(
        draw(
            st.lists(
                st.decimals(min_value=Decimal("0.001"), max_value=1000, places=3),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
    )
    median = draw(
        st.one_of(
            st.sampled_from([low, high]), st.decimals(min_value=low, max_value=high)
        )
    )
    spread = draw(st.decimals(min_value=Decimal("0.0001"), max_value=10, places=4))
    return Range(
        min=low,
        max=high,
        distribution="lognormal",
        median=median.quantize(Decimal("0.001")).max(low).min(high),
        spread=spread,
    )


CONTROLS = [
    normal("1.000", "9.000", "1.000", "100000000000000000000.000"),
    normal("1.000", "9.000", "1.000", "10000000.000"),
    normal("1.000", "9.000", "2.000", "80.001"),
    normal("1.000", "9.000", "2.000", "80.000"),
    normal("38.000", "60.000", "40.000", "5.000"),
    normal("10.000", "11.000", "10.000", "0.001"),
]


LOGNORMAL_CONTROLS = [
    lognormal("100000.000", "100000.001", "100000.000", "10.0000"),
    lognormal("999999.998", "999999.999", "999999.999", "10.0000"),
    lognormal("1.000", "1.105", "1.000", "1.0000"),
    lognormal("1.000", "1.106", "1.000", "1.0000"),
    lognormal("1.000", "100.000", "4.000", "10.0000"),
    lognormal("10.000", "1000.000", "1000.000", "0.0001"),
]


FROZEN_BOUNDS = Path(__file__).parent / "frozen-world" / "draws-at-bounds.json"


# The uniform numbers at the bounds of a slot, 0, the smallest above 0 and the largest
# below 1, and five between.
BOUND_UNIFORMS = (
    "0",
    "1.1102230246251565e-16",
    "0.01",
    "0.25",
    "0.5",
    "0.75",
    "0.99",
    "0.9999999999999999",
)


# A range of each kind of draw, the normal and lognormal ones also narrow and with
# their mean or median at a bound and the other bound far in a tail.
BOUND_RANGES = {
    "uniform": DEMAND,
    "triangular": triangular("4.8000", "5.5000", "5.0000"),
    "normal": normal("30.000", "50.000", "40.000", "5.000"),
    "normal with its mean at a bound": normal("40.000", "70.000", "40.000", "5.000"),
    "narrow normal": normal("1.000", "9.000", "5.000", "100000000000000000000.000"),
    "lognormal": lognormal("20.000", "120.000", "40.000", "0.5000"),
    "lognormal with its median at a bound": lognormal(
        "20.000", "40.000", "40.000", "0.0100"
    ),
    "narrow lognormal": lognormal("100000.000", "100000.001", "100000.000", "10.0000"),
}


# Every draw of each range at each of the uniform numbers and its mean, and the shared
# demand of three common shares at pairs of them, written as JSON.
def draws_at_bounds_text() -> bytes:
    uniforms = [Decimal(uniform) for uniform in BOUND_UNIFORMS]
    table: dict[str, Any] = {
        name: {
            "draws": [draw_value(value_range, uniform) for uniform in uniforms],
            "mean": range_mean(value_range),
        }
        for name, value_range in BOUND_RANGES.items()
    }
    for share in ("0.5000", "0.9000", "1.0000"):
        draws = [
            draw_value(DEMAND, combine_demand_draws(common, own, Decimal(share)))
            for common, own in zip(uniforms, reversed(uniforms), strict=True)
        ]
        table[f"shared demand of common share {share}"] = {"draws": draws}
    return write_json(table) + b"\n"


@st.composite
def symmetric_normal_ranges(draw: st.DrawFn) -> Range[Decimal]:
    half = draw(st.decimals(min_value=Decimal("0.001"), max_value=500, places=3))
    centre = draw(st.decimals(min_value=half, max_value=1000, places=3))
    sd = draw(
        st.one_of(
            st.decimals(min_value=Decimal("0.001"), max_value=1000, places=3), large_sds
        )
    )
    return Range(
        min=centre - half,
        max=centre + half,
        distribution="normal",
        mean=centre,
        sd=sd,
    )


# The base demand of every period: the first draw, then p times the base before plus
# 1 - p times the draw, half to even to 3 places.
def carried_by_rule(
    draws: tuple[Decimal, ...], persistence: Decimal
) -> tuple[Decimal, ...]:
    bases = [draws[0]]
    with localcontext(CONTEXT):
        for draw in draws[1:]:
            base = persistence * bases[-1] + (1 - persistence) * draw
            bases.append(base.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN))
    return tuple(bases)


def test_a_number_of_periods_is_drawn_by_the_floor_of_its_share_of_the_range():
    periods = Range(min=1, max=2)

    # 1 + floor(0.25 * 2) = 1 and 1 + floor(0.75 * 2) = 2.
    assert draw_periods(periods, Decimal("0.25")) == 1
    assert draw_periods(periods, Decimal("0.75")) == 2


def test_a_uniform_draw_moves_from_min_by_its_share_of_the_range():
    share_range = Range(min=Decimal("0.8000"), max=Decimal("0.9200"))
    value = draw_value(share_range, Decimal("0.25"))
    assert value.as_tuple() == Decimal("0.8300").as_tuple()


def test_a_tie_of_a_drawn_value_rounds_half_to_even():
    low = Range(min=Decimal("0.000"), max=Decimal("0.001"))
    high = Range(min=Decimal("0.001"), max=Decimal("0.002"))

    assert draw_value(low, Decimal("0.5")).as_tuple() == Decimal("0.000").as_tuple()
    assert draw_value(high, Decimal("0.5")).as_tuple() == Decimal("0.002").as_tuple()


def test_a_triangular_draw_follows_its_two_branches():
    quantity = triangular("0.000", "10.000", "4.000")
    price = triangular("4.8000", "5.5000", "5.0000")

    assert draw_value(quantity, Decimal("0.1")) == Decimal("2.000")
    assert draw_value(quantity, Decimal("0.6")) == Decimal("5.101")
    assert draw_value(quantity, Decimal("0.4")) == Decimal("4.000")
    assert draw_value(price, Decimal("0.1")) == Decimal("4.9183")
    assert draw_value(price, Decimal("0.9")) == Decimal("5.3129")


@pytest.mark.parametrize("uniform", ["0", "0.5", "1"])
def test_a_triangular_range_whose_min_equals_its_max_draws_that_value(uniform: str):
    value = draw_value(triangular("2.000", "2.000", "2.000"), Decimal(uniform))

    assert str(value) == "2.000"


def test_a_normal_draw_is_cut_to_its_range():
    demand = normal("30.000", "50.000", "40.000", "5.000")

    assert draw_value(demand, Decimal("0.5")) == Decimal("40.000")
    assert draw_value(demand, Decimal("0.25")) == Decimal("36.804")


# u = 0.5 takes the quartile of the half normal above 10: 10 + 0.001 * 0.6745 = 10.0007.
def test_a_normal_range_whose_max_lies_far_in_a_tail_draws_near_its_mean():
    far = normal("10.000", "11.000", "10.000", "0.001")

    assert draw_value(far, Decimal("0.5")) == Decimal("10.001")


# An sd of 10**20 leaves the cut distribution flat to one part in 10**38, so u = 0.01
# draws `1 + 8 * 0.01 = 1.08`.
def test_a_normal_range_far_narrower_than_its_sd_draws_evenly_over_it():
    narrow = normal("1.000", "9.000", "5.000", "100000000000000000000.000")

    draws = [draw_value(narrow, Decimal(quantile)) for quantile in QUANTILES]

    assert draws == [
        Decimal(text) for text in ("1.080", "3.000", "5.000", "7.000", "8.920")
    ]


def test_a_lognormal_draw_is_cut_to_its_range():
    demand = lognormal("20.000", "120.000", "40.000", "0.5000")

    assert draw_value(demand, Decimal("0.5")) == Decimal("41.765")
    assert draw_value(demand, Decimal("0.1")) == Decimal("24.977")
    assert draw_value(demand, Decimal("0.9")) == Decimal("75.004")


def test_a_lognormal_draw_with_its_median_at_a_bound_stays_within_its_range():
    demand = lognormal("20.000", "40.000", "40.000", "0.0100")

    assert draw_value(demand, Decimal("0")) == Decimal("27.227")
    assert draw_value(demand, Decimal("0.5")) == Decimal("39.731")


def test_a_target_is_chosen_by_the_smallest_draw_and_a_tie_by_the_first():
    assert choose_target({"b": Decimal("0.2"), "a": Decimal("0.3")}) == "b"
    assert choose_target({"b": Decimal("0.2"), "a": Decimal("0.2")}) == "a"


def test_the_mean_of_a_lognormal_range_is_the_mean_of_its_cut_distribution():
    wide = lognormal("10", "200", "40", "0.5")
    narrow = lognormal("14", "70", "35", "0.4")

    assert round(range_mean(wide), 3) == Decimal("45.308")
    assert round(range_mean(narrow), 3) == Decimal("36.222")


def test_the_mean_of_a_lognormal_range_holds_up_to_the_largest_spread():
    assert round(range_mean(lognormal("1", "100", "4", "10")), 6) == Decimal(
        "21.145162"
    )
    assert round(range_mean(lognormal("1", "100", "4", "0.4")), 6) == Decimal(
        "4.334054"
    )


def test_the_mean_of_a_normal_range_is_the_mean_of_its_cut_distribution():
    assert round(range_mean(normal("38", "60", "40", "5")), 3) == Decimal("42.809")


# The half normal above its mean has the mean 10 + 0.001 * sqrt(2 / pi) = 10.000798.
def test_a_normal_range_whose_max_lies_far_in_a_tail_counts_at_the_half_normal_mean():
    assert range_mean(normal("10.000", "11.000", "10.000", "0.001")) == Decimal(
        "10.000798"
    )


# Across 1 to 9 an sd of 10**20 changes the density by less than one part in 10**38;
# the cut distribution is symmetric about 5, so its mean is 5.
def test_the_mean_of_a_normal_range_far_narrower_than_its_sd_is_its_center():
    narrow = normal("1.000", "9.000", "5.000", "100000000000000000000.000")

    assert range_mean(narrow) == Decimal("5.000000")


@pytest.mark.parametrize("value_range", CONTROLS)
def test_the_mean_of_a_normal_range_is_the_mean_of_the_oracle(
    value_range: Range[Decimal],
):
    assert range_mean(value_range) == oracle_normal_mean(value_range)


@pytest.mark.parametrize("value_range", CONTROLS)
def test_a_normal_draw_is_the_value_of_the_oracle(value_range: Range[Decimal]):
    for uniform in QUANTILES:
        expected = oracle_normal_value(value_range, Decimal(uniform))
        assert draw_value(value_range, Decimal(uniform)) == expected


# ln(max / min) is 10**-8, so the density changes by about one part in 10**8 across
# the range and the mean is its middle, 100000.0005.
def test_the_mean_of_a_lognormal_range_far_narrower_than_its_spread_is_its_middle():
    narrow = lognormal("100000.000", "100000.001", "100000.000", "10.0000")

    assert range_mean(narrow) == Decimal("100000.000500")


# ln(max / min) is 8 * 10**-15, so the range is flat to about one part in 10**14 and u
# draws `10**12 + 0.008 * u`.
def test_a_lognormal_range_far_narrower_than_its_spread_draws_evenly_over_it():
    narrow = lognormal(
        "1000000000000.000", "1000000000000.008", "1000000000000.004", "1.0000"
    )

    draws = [draw_value(narrow, Decimal(quantile)) for quantile in QUANTILES]

    assert [draw - narrow.min for draw in draws] == [
        Decimal(text) for text in ("0.000", "0.002", "0.004", "0.006", "0.008")
    ]


@pytest.mark.parametrize("value_range", LOGNORMAL_CONTROLS)
def test_the_mean_of_a_lognormal_range_is_the_mean_of_the_oracle(
    value_range: Range[Decimal],
):
    assert range_mean(value_range) == oracle_lognormal_mean(value_range)


@pytest.mark.parametrize("value_range", LOGNORMAL_CONTROLS)
def test_a_lognormal_draw_is_the_value_of_the_oracle(value_range: Range[Decimal]):
    for uniform in QUANTILES:
        expected = oracle_lognormal_value(value_range, Decimal(uniform))
        assert draw_value(value_range, Decimal(uniform)) == expected


def test_the_mean_of_a_triangular_range_is_the_mean_of_its_three_points():
    assert range_mean(triangular("3", "8", "4")) == 5


def test_the_mean_of_a_uniform_range_is_the_middle_of_its_bounds():
    assert range_mean(Range(min=Decimal(2), max=Decimal(6))) == 4
    assert range_mean(Range(min=1, max=4)) == Decimal("2.5")


def test_an_outage_in_period_6_raises_the_chance_of_delays_in_periods_7_and_8():
    chances = raised_chances(DELAYS_CHANCE, [(6, RAISE_DELAYS)], horizon=10)

    assert chances[6:9] == (Decimal("0.3000"), Decimal("0.3000"), Decimal("0.1000"))
    assert chances[:6] == (DELAYS_CHANCE,) * 6
    assert is_within_chance(chances[6], Decimal("0.2500"))
    assert not is_within_chance(chances[8], Decimal("0.2500"))
    assert not is_within_chance(chances[7], Decimal("0.3000"))


def test_a_raised_chance_is_at_most_1():
    cascade = Cascade(rule="delays", factor=Decimal("15.0000"), periods=2)

    chances = raised_chances(DELAYS_CHANCE, [(6, cascade)], horizon=10)

    assert chances[6:8] == (Decimal(1), Decimal(1))


def test_overlapping_windows_raise_the_chance_once_until_the_later_one_ends():
    chances = raised_chances(
        DELAYS_CHANCE, [(6, RAISE_DELAYS), (7, RAISE_DELAYS)], horizon=10
    )

    assert chances[6:10] == (
        Decimal("0.3000"),
        Decimal("0.3000"),
        Decimal("0.3000"),
        Decimal("0.1000"),
    )


def test_a_window_longer_than_the_horizon_is_cut_to_the_horizon():
    cascade = Cascade(rule="delays", factor=Decimal("2"), periods=10**9)

    chances = raised_chances(Decimal("0.1"), [(1, cascade)], horizon=5)

    assert chances == tuple(
        Decimal(text) for text in ("0.1", "0.2", "0.2", "0.2", "0.2")
    )


def test_a_chance_happens_below_it_only():
    assert is_within_chance(Decimal("0.0100"), Decimal("0.0042"))
    assert not is_within_chance(Decimal("0.0100"), Decimal("0.0100"))


def test_a_half_shared_draw_mixes_the_common_and_the_own_draw():
    uniform = combine_demand_draws(Decimal("0.8"), Decimal("0.5"), Decimal("0.5000"))

    assert uniform == Decimal("0.724117060095737")
    assert draw_value(DEMAND, uniform) == Decimal("44.482")


def test_opposite_draws_cancel_but_for_floating_point():
    uniform = combine_demand_draws(Decimal("0.8"), Decimal("0.2"), Decimal("0.5000"))

    assert uniform == Decimal("0.5000000000000001")
    assert draw_value(DEMAND, uniform) == Decimal("40.000")


def test_a_common_share_of_0_keeps_the_own_draw_exactly():
    uniform = combine_demand_draws(Decimal("0.8"), Decimal("0.5"), Decimal("0"))

    assert uniform.as_tuple() == Decimal("0.5").as_tuple()


def test_a_common_share_of_1_takes_the_common_draw_for_every_own_draw():
    for own in ("0.1", "0.5", "0.99"):
        uniform = combine_demand_draws(Decimal("0.8"), Decimal(own), Decimal("1.0000"))
        assert uniform == Decimal("0.8")


def test_the_draws_of_every_distribution_at_its_bounds_are_the_same_as_frozen():
    assert draws_at_bounds_text() == FROZEN_BOUNDS.read_bytes()


def test_persistence_carries_half_of_the_previous_base_into_the_next():
    draws = (Decimal("40.000"), Decimal("50.000"), Decimal("30.000"))

    assert carry_demand_over(draws, Decimal("0.5000")) == (
        Decimal("40.000"),
        Decimal("45.000"),
        Decimal("37.500"),
    )


def test_persistence_rounds_each_base_half_to_even():
    draws = (Decimal("10.000"), Decimal("10.001"))

    # 0.5 * 10.000 + 0.5 * 10.001 = 10.0005; half to even gives 10.000, half up 10.001.
    assert carry_demand_over(draws, Decimal("0.5000")) == (
        Decimal("10.000"),
        Decimal("10.000"),
    )


@pytest.mark.property
@given(st.one_of(triangular_ranges(), normal_ranges(), lognormal_ranges()), u_values)
def test_a_triangular_normal_or_lognormal_draw_lies_within_its_range_with_its_places(
    value_range: Range[Decimal], uniform: Decimal
):
    value = draw_value(value_range, uniform)

    assert value_range.min <= value <= value_range.max
    assert value == value.quantize(Decimal("0.001"))


@pytest.mark.property
@given(st.one_of(triangular_ranges(), normal_ranges(), lognormal_ranges()))
def test_the_mean_of_a_range_lies_within_its_bounds(value_range: Range[Decimal]):
    assert value_range.min <= range_mean(value_range) <= value_range.max


@pytest.mark.property
@given(symmetric_normal_ranges())
def test_the_mean_of_a_symmetric_normal_range_is_its_center(
    value_range: Range[Decimal],
):
    assert range_mean(value_range) == value_range.mean


@pytest.mark.property
@given(st.one_of(normal_ranges(), lognormal_ranges()))
def test_the_mean_of_a_normal_or_lognormal_range_is_the_mean_of_the_oracle(
    value_range: Range[Decimal],
):
    if value_range.distribution == "normal":
        expected = oracle_normal_mean(value_range)
    else:
        expected = oracle_lognormal_mean(value_range)

    assert abs(range_mean(value_range) - expected) <= Decimal("0.000001")


# Two draws differ when the values of the oracle lie more than 0.002 apart, so a
# rounding of either draw cannot close the gap.
@pytest.mark.property
@given(normal_ranges(), u_values, u_values)
def test_normal_draws_rise_with_u_and_differ_where_their_values_differ(
    value_range: Range[Decimal], first: Decimal, second: Decimal
):
    low, high = sorted((first, second))

    assert draw_value(value_range, low) <= draw_value(value_range, high)
    if oracle_normal_value(value_range, high) - oracle_normal_value(
        value_range, low
    ) > Decimal("0.002"):
        assert draw_value(value_range, low) < draw_value(value_range, high)


@pytest.mark.property
@given(
    st.decimals(min_value=0, max_value=1, places=4),
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=12),
            st.decimals(min_value=Decimal("1.0001"), max_value=20, places=4),
            st.integers(min_value=1, max_value=4),
        ),
        max_size=4,
    ),
)
def test_a_raised_chance_holds_in_its_windows_only_and_stays_from_0_to_1(
    chance: Decimal, starts: list[tuple[int, Decimal, int]]
):
    windows = [
        (start, Cascade(rule="delays", factor=factor, periods=periods))
        for start, factor, periods in starts
    ]

    chances = raised_chances(chance, windows, horizon=12)

    for period, raised in enumerate(chances, start=1):
        holding = [
            cascade.factor
            for start, cascade in windows
            if start < period <= start + cascade.periods
        ]
        if holding:
            assert raised == min(Decimal(1), chance * max(holding))
        else:
            assert raised == chance
        assert 0 <= raised <= 1


@pytest.mark.property
@given(common_shares, uniforms, uniforms, st.data())
def test_a_shared_draw_stays_within_its_range_with_3_places(
    common_share: Decimal, common: Decimal, own: Decimal, data: st.DataObject
):
    low, high = sorted(
        data.draw(st.lists(quantities, min_size=2, max_size=2)), key=Decimal
    )
    demand = Range(min=Decimal(low), max=Decimal(high))

    drawn = draw_value(demand, combine_demand_draws(common, own, common_share))

    assert demand.min <= drawn <= demand.max
    assert drawn.as_tuple().exponent == -3


@pytest.mark.property
@given(
    st.lists(
        st.decimals(min_value=0, max_value=1000, places=3), min_size=1, max_size=12
    ),
    st.decimals(min_value=0, max_value=1, places=4),
)
def test_base_demand_with_persistence_stays_within_its_draws(
    draws: list[Decimal], persistence: Decimal
):
    bases = carry_demand_over(tuple(draws), persistence)

    assert all(min(draws) <= base <= max(draws) for base in bases)
    assert carry_demand_over(tuple(draws), Decimal(0)) == tuple(draws)


@pytest.mark.property
@given(small_factories(), seeds, st.decimals(min_value=0, max_value=1, places=4))
def test_persistence_leaves_the_draws_of_every_pair(
    factory: FactoryBodies, seed: int, persistence: Decimal
):
    manifest, scenario = factory
    for customer in manifest["customers"].values():
        for terms in customer["products"].values():
            terms.pop("demand_persistence", None)
    plain = draw_world_of_bodies(manifest, scenario, seed=seed)
    pairs = [
        terms
        for customer in manifest["customers"].values()
        for terms in customer["products"].values()
        if isinstance(terms["demand"], dict)
    ]
    assume(pairs)
    pairs[0]["demand_persistence"] = str(persistence)
    carried = draw_world_of_bodies(manifest, scenario, seed=seed)

    for pair, bases in carried.demand.items():
        persisting = (
            carried.factory.customers[pair.split("/")[0]]
            .products[pair.split("/")[1]]
            .demand_persistence
        )
        assert bases == carried_by_rule(plain.demand[pair], persisting or Decimal(0))
