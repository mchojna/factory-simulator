"""The values drawn from uniform numbers: ranges, periods, chances, targets, demand.

Examples:
    >>> draw_value(Range(min=Decimal("10.000"), max=Decimal("20.000")), Decimal("0.5"))
    Decimal('15.000')
"""

import math
from collections.abc import Callable, Iterable, Mapping
from decimal import ROUND_FLOOR, Decimal
from statistics import NormalDist
from typing import cast

from numpy.random import Generator

from factory_simulator.engine.draws.streams import draw_uniform
from factory_simulator.engine.models.manifest import (
    DecimalParameter,
    PeriodsParameter,
    Range,
)
from factory_simulator.engine.models.scenario import Cascade
from factory_simulator.engine.numbers import in_decimal_context, round_to

# A normal or lognormal range is narrow when its bounds lie less than this many
# standard deviations apart.
NARROW = Decimal("0.1")

# The nodes and weights of the Gauss-Legendre rule of 6 points from -1 to 1.
GAUSS_LEGENDRE = (
    (-0.932469514203152, 0.17132449237917036),
    (-0.6612093864662645, 0.3607615730481386),
    (-0.2386191860831969, 0.46791393457269104),
    (0.2386191860831969, 0.46791393457269104),
    (0.6612093864662645, 0.3607615730481386),
    (0.932469514203152, 0.17132449237917036),
)


@in_decimal_context
def draw_value(value_range: Range[Decimal], uniform: Decimal) -> Decimal:
    """Draw a value from a range with a uniform number.

    With a the `min`, b the `max` and u the uniform number, a range whose `min`
    equals its `max` gives that value. A uniform range gives `a + (b - a) * u`. A
    triangular range with mode c gives `a + sqrt(u * (b - a) * (c - a))` below
    `u = (c - a) / (b - a)` and `b - sqrt((1 - u) * (b - a) * (b - c))` from there. A
    normal or lognormal range is cut to its bounds: u is spread over the share of the
    distribution within them.

    Args:
        value_range (Range[Decimal]): The range, its bounds at the places of their kind.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        Decimal: The value, rounded half to even to the places of `min` and kept
            within the range.

    Examples:
        >>> draw_value(
        ...     Range(min=Decimal("10.000"), max=Decimal("20.000")), Decimal("0.5")
        ... )
        Decimal('15.000')
    """
    low, high = value_range.min, value_range.max
    if low == high:
        return low
    if value_range.distribution == "triangular":
        mode = cast(Decimal, value_range.mode)
        if uniform < (mode - low) / (high - low):
            value = low + (uniform * (high - low) * (mode - low)).sqrt()
        else:
            value = high - ((1 - uniform) * (high - low) * (high - mode)).sqrt()
    elif value_range.distribution == "normal":
        value = normal_value(value_range, uniform)
    elif value_range.distribution == "lognormal":
        value = lognormal_value(value_range, uniform)
    else:
        value = low + (high - low) * uniform
    return min(max(value.quantize(low), low), high)


def normal_value(value_range: Range[Decimal], uniform: Decimal) -> Decimal:
    """Give the value of a normal range cut to its bounds at a uniform number.

    The uniform number u is spread over the share of the distribution within `min`
    to `max`. A narrow range, whose bounds lie less than 0.1 standard deviations
    apart, takes `mean + sd * z` with z the value of `narrow_cut_value` in standard
    deviations.

    Args:
        value_range (Range[Decimal]): The range, with its mean from `min` to `max`
            and its standard deviation.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        Decimal: The value before rounding.

    Examples:
        >>> normal = Range(
        ...     min=Decimal("0"),
        ...     max=Decimal("10"),
        ...     distribution="normal",
        ...     mean=Decimal("5"),
        ...     sd=Decimal("1"),
        ... )
        >>> normal_value(normal, Decimal("0.5"))
        Decimal('5.0')
    """
    mean, sd = cast(Decimal, value_range.mean), cast(Decimal, value_range.sd)
    low_z, high_z = standard_bounds(value_range)
    if high_z - low_z < NARROW:
        z = narrow_cut_value(float(low_z), float(high_z), float(uniform))
        return mean + sd * Decimal(repr(z))
    curve = NormalDist(float(mean), float(sd))
    below = curve.cdf(float(value_range.min))
    within = curve.cdf(float(value_range.max)) - below
    share = open_unit(below + float(uniform) * within)
    return Decimal(repr(curve.inv_cdf(share)))


def lognormal_value(value_range: Range[Decimal], uniform: Decimal) -> Decimal:
    """Give the value of a lognormal range cut to its bounds at a uniform number.

    The natural logarithm of the value is normal with mean `log(median)` and standard
    deviation `spread`; u is spread over the share of it within `log(min)` to
    `log(max)`. A narrow range, whose `log(max / min)` is less than 0.1 spread, takes
    `median * exp(spread * z)` with z the value of `narrow_cut_value` in spreads.

    Args:
        value_range (Range[Decimal]): The range, with its median from `min` to `max`
            and its spread.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        Decimal: The value before rounding.

    Examples:
        >>> lognormal = Range(
        ...     min=Decimal("1"),
        ...     max=Decimal("100"),
        ...     distribution="lognormal",
        ...     median=Decimal("10"),
        ...     spread=Decimal("1"),
        ... )
        >>> lognormal_value(lognormal, Decimal("0.5"))
        Decimal('10.000000000000002')
    """
    median = cast(Decimal, value_range.median)
    spread = cast(Decimal, value_range.spread)
    low_z, high_z = standard_bounds(value_range)
    if high_z - low_z < NARROW:
        z = narrow_cut_value(float(low_z), float(high_z), float(uniform))
        return median * (spread * Decimal(repr(z))).exp()
    curve = NormalDist(math.log(float(median)), float(spread))
    below = curve.cdf(math.log(float(value_range.min)))
    within = curve.cdf(math.log(float(value_range.max))) - below
    share = open_unit(below + float(uniform) * within)
    return Decimal(repr(math.exp(curve.inv_cdf(share))))


def standard_bounds(value_range: Range[Decimal]) -> tuple[Decimal, Decimal]:
    """Give the bounds of a normal or lognormal range in standard deviations.

    A normal range gives `(min - mean) / sd` and `(max - mean) / sd`, a lognormal
    range `ln(min / median) / spread` and `ln(max / median) / spread`, in decimals.

    Args:
        value_range (Range[Decimal]): The normal or lognormal range.

    Returns:
        tuple[Decimal, Decimal]: The lower and the upper bound.

    Examples:
        >>> normal = Range(
        ...     min=Decimal(1),
        ...     max=Decimal(9),
        ...     distribution="normal",
        ...     mean=Decimal(5),
        ...     sd=Decimal(2),
        ... )
        >>> standard_bounds(normal)
        (Decimal('-2'), Decimal('2'))
    """
    low, high = value_range.min, value_range.max
    if value_range.distribution == "normal":
        mean, sd = cast(Decimal, value_range.mean), cast(Decimal, value_range.sd)
        return (low - mean) / sd, (high - mean) / sd
    median = cast(Decimal, value_range.median)
    spread = cast(Decimal, value_range.spread)
    return (low / median).ln() / spread, (high / median).ln() / spread


def narrow_cut_value(low: float, high: float, uniform: float) -> float:
    """Give the value of the standard normal cut between two close bounds at u.

    With `E` the error function and u the uniform number,
    `t = E(low / sqrt(2)) + u * (E(high / sqrt(2)) - E(low / sqrt(2)))`; three steps
    of Newton's method from `w = t * sqrt(pi) / 2` solve `E(w) = t`, and the value is
    `w * sqrt(2)`.

    Args:
        low (float): The lower bound, in standard deviations, at most 0.
        high (float): The upper bound, in standard deviations, at least 0 and less
            than 0.1 above `low`.
        uniform (float): A uniform number from 0 to 1.

    Returns:
        float: The value, in standard deviations.

    Examples:
        >>> narrow_cut_value(-0.05, 0.05, 0.5)
        0.0
    """
    low_share, high_share = math.erf(low / math.sqrt(2)), math.erf(high / math.sqrt(2))
    target = low_share + uniform * (high_share - low_share)
    root = target * math.sqrt(math.pi) / 2
    for _ in range(3):
        root -= (math.erf(root) - target) * math.sqrt(math.pi) / 2 * math.exp(root**2)
    return root * math.sqrt(2)


@in_decimal_context
def range_mean(value_range: Range[Decimal] | Range[int]) -> Decimal:
    """Give the mean of a range cut to its bounds.

    A uniform range and a range of periods give `(min + max) / 2`, a triangular range
    `(min + mode + max) / 3`. A normal or lognormal range gives the mean of its
    distribution cut to `min` and `max`.

    Args:
        value_range (Range[Decimal] | Range[int]): The range; a normal range has its
            mean and a lognormal range its median from `min` to `max`.

    Returns:
        Decimal: The mean, kept within the range and rounded half to even to 6 places.

    Examples:
        >>> range_mean(Range(min=1, max=4))
        Decimal('2.500000')
        >>> range_mean(
        ...     Range(
        ...         min=Decimal(38),
        ...         max=Decimal(60),
        ...         distribution="normal",
        ...         mean=Decimal(40),
        ...         sd=Decimal(5),
        ...     )
        ... )
        Decimal('42.808528')
    """
    low, high = Decimal(value_range.min), Decimal(value_range.max)
    if isinstance(value_range.min, int) or value_range.distribution == "uniform":
        mean = (low + high) / 2
    elif value_range.distribution == "triangular":
        mean = (low + cast(Decimal, value_range.mode) + high) / 3
    elif value_range.distribution == "normal":
        mean = normal_mean(cast(Range[Decimal], value_range))
    else:
        mean = lognormal_mean(cast(Range[Decimal], value_range))
    return round_to(min(max(mean, low), high), 6)


def normal_mean(value_range: Range[Decimal]) -> Decimal:
    """Give the mean of a normal range cut to its bounds.

    With `za = (min - mean) / sd`, `zb = (max - mean) / sd` and the standard normal,
    the mean is `mean + sd * (pdf(za) - pdf(zb)) / (cdf(zb) - cdf(za))`. A narrow
    range, whose bounds lie less than 0.1 standard deviations apart, takes
    `mean + sd * m` with m the mean of z by `narrow_cut_mean`.

    Args:
        value_range (Range[Decimal]): The range, with its mean from `min` to `max`
            and its standard deviation.

    Returns:
        Decimal: The mean before rounding.

    Examples:
        >>> normal = Range(
        ...     min=Decimal(0),
        ...     max=Decimal(10),
        ...     distribution="normal",
        ...     mean=Decimal(5),
        ...     sd=Decimal(1),
        ... )
        >>> normal_mean(normal)
        Decimal('5.0')
    """
    mean, sd = cast(Decimal, value_range.mean), cast(Decimal, value_range.sd)
    low_z, high_z = standard_bounds(value_range)
    if high_z - low_z < NARROW:
        center = narrow_cut_mean(float(low_z), float(high_z), lambda z: z)
        return mean + sd * Decimal(repr(center))
    standard = NormalDist()
    low = (float(value_range.min) - float(mean)) / float(sd)
    high = (float(value_range.max) - float(mean)) / float(sd)
    within = standard.cdf(high) - standard.cdf(low)
    cut = float(mean) + float(sd) * (standard.pdf(low) - standard.pdf(high)) / within
    return Decimal(repr(cut))


def lognormal_mean(value_range: Range[Decimal]) -> Decimal:
    """Give the mean of a lognormal range cut to its bounds.

    With `mu = ln(median)`, s the spread, `za = (ln(min) - mu) / s`,
    `zb = (ln(max) - mu) / s` and the standard normal, the mean is
    `exp(mu + s * s / 2) * (cdf(zb - s) - cdf(za - s)) / (cdf(zb) - cdf(za))`. A narrow
    range, whose `ln(max / min)` is less than 0.1 s, takes
    `median * exp(s * c) * (1 + m)` with c the middle of `za` and `zb` and m the mean
    of `expm1(s * (z - c))` by `narrow_cut_mean`.

    Args:
        value_range (Range[Decimal]): The range, with its median from `min` to `max`
            and its spread.

    Returns:
        Decimal: The mean before rounding.

    Examples:
        >>> lognormal = Range(
        ...     min=Decimal(14),
        ...     max=Decimal(70),
        ...     distribution="lognormal",
        ...     median=Decimal(35),
        ...     spread=Decimal("0.4"),
        ... )
        >>> round(lognormal_mean(lognormal), 6)
        Decimal('36.222159')
    """
    median = cast(Decimal, value_range.median)
    spread = cast(Decimal, value_range.spread)
    low_z, high_z = standard_bounds(value_range)
    if high_z - low_z < NARROW:
        middle = (low_z + high_z) / 2
        rise = narrow_cut_mean(
            float(low_z),
            float(high_z),
            lambda z: math.expm1(float(spread) * (z - float(middle))),
        )
        return median * (spread * middle).exp() * (1 + Decimal(repr(rise)))
    standard = NormalDist()
    center, width = math.log(float(median)), float(spread)
    low = (math.log(float(value_range.min)) - center) / width
    high = (math.log(float(value_range.max)) - center) / width
    within = standard.cdf(high) - standard.cdf(low)
    shifted = standard.cdf(high - width) - standard.cdf(low - width)
    cut = math.exp(center + width * width / 2) * shifted / within
    return Decimal(repr(cut))


def narrow_cut_mean(low: float, high: float, value: Callable[[float], float]) -> float:
    """Give the mean of a value of the standard normal cut between two close bounds.

    The Gauss-Legendre rule of 6 points integrates `value(z) * exp(-z * z / 2)` and
    `exp(-z * z / 2)` from `low` to `high`; the mean is the first over the second.

    Args:
        low (float): The lower bound, in standard deviations.
        high (float): The upper bound, in standard deviations, less than 0.1 above
            `low`.
        value (Callable[[float], float]): The value of each z.

    Returns:
        float: The mean of the value.

    Examples:
        >>> round(narrow_cut_mean(0.0, 0.08, lambda z: z), 6)
        0.039979
    """
    center, half = (low + high) / 2, (high - low) / 2
    total = weighted = 0.0
    for node, weight in GAUSS_LEGENDRE:
        z = center + half * node
        density = weight * math.exp(-z * z / 2)
        total += density
        weighted += density * value(z)
    return weighted / total


@in_decimal_context
def combine_demand_draws(
    common: Decimal, own: Decimal, common_share: Decimal
) -> Decimal:
    """Combine the common draw of a product with the own draw of a customer product.

    With s the common share and N the standard normal,
    `z = sqrt(s) * N.inv_cdf(common) + sqrt(1 - s) * N.inv_cdf(own)`, and the result
    is `N.cdf(z)`. With s at 0 the own draw comes back unchanged.

    Args:
        common (Decimal): The uniform number of the product in the period.
        own (Decimal): The uniform number of the customer product in the period.
        common_share (Decimal): The share s of the variation the customers of the
            product have in common, from 0 to 1.

    Returns:
        Decimal: A uniform number from 0 to 1, with the digits of its shortest text.

    Examples:
        >>> combine_demand_draws(Decimal("0.8"), Decimal("0.5"), Decimal("0.5000"))
        Decimal('0.724117060095737')
    """
    if common_share == 0:
        return own
    curve = NormalDist()
    share = float(common_share)
    mixed = math.sqrt(share) * curve.inv_cdf(open_unit(float(common))) + math.sqrt(
        1 - share
    ) * curve.inv_cdf(open_unit(float(own)))
    return Decimal(repr(curve.cdf(mixed)))


def open_unit(share: float) -> float:
    """Give a share kept above 0 and below 1, where the inverse of a normal is defined.

    Args:
        share (float): A number from 0 to 1.

    Returns:
        float: The number, moved to the nearest float above 0 or below 1 when it
            sits on a bound.

    Examples:
        >>> open_unit(0.0) > 0
        True
    """
    return min(max(share, math.nextafter(0.0, 1.0)), math.nextafter(1.0, 0.0))


def draw_periods(value_range: Range[int], uniform: Decimal) -> int:
    """Draw a whole number of periods from a range with a uniform number.

    Args:
        value_range (Range[int]): The range.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        int: `min + floor(u * (max - min + 1))` for the uniform number u, at most
            `max`.

    Examples:
        >>> draw_periods(Range(min=1, max=3), Decimal("0.999"))
        3
    """
    low, high = value_range.min, value_range.max
    steps = (uniform * (high - low + 1)).to_integral_value(rounding=ROUND_FLOOR)
    return min(low + int(steps), high)


@in_decimal_context
def carry_demand_over(
    draws: tuple[Decimal, ...], persistence: Decimal
) -> tuple[Decimal, ...]:
    """Carry a share of each base demand into the next period.

    `base(1) = draw(1)` and `base(t) = p * base(t - 1) + (1 - p) * draw(t)`, each
    rounded half to even to 3 places.

    Args:
        draws (tuple[Decimal, ...]): The drawn demand of every period.
        persistence (Decimal): The share p carried over, from 0 to 1.

    Returns:
        tuple[Decimal, ...]: The base demand of every period.

    Examples:
        >>> carry_demand_over((Decimal("40.000"), Decimal("50.000")), Decimal("0.5"))
        (Decimal('40.000'), Decimal('45.000'))
    """
    bases: list[Decimal] = []
    for draw in draws:
        if not bases:
            bases.append(draw)
            continue
        base = persistence * bases[-1] + (1 - persistence) * draw
        bases.append(round_to(base, 3))
    return tuple(bases)


@in_decimal_context
def choose_target(draws: Mapping[str, Decimal]) -> str:
    """Choose the target with the smallest draw; a tie goes to the first identifier.

    Args:
        draws (Mapping[str, Decimal]): The uniform number of each target.

    Returns:
        str: The identifier chosen.

    Examples:
        >>> choose_target({"b": Decimal("0.2"), "a": Decimal("0.3")})
        'b'
    """
    return min(sorted(draws), key=lambda target: draws[target])


@in_decimal_context
def is_within_chance(chance: Decimal, uniform: Decimal) -> bool:
    """Tell whether something with a chance happens, given a uniform number.

    Args:
        chance (Decimal): The chance, from 0 to 1.
        uniform (Decimal): A uniform number from 0 to 1.

    Returns:
        bool: True when the uniform number is below the chance.

    Examples:
        >>> is_within_chance(Decimal("0.0200"), Decimal("0.01"))
        True
    """
    return uniform < chance


@in_decimal_context
def raised_chances(
    chance: Decimal, windows: Iterable[tuple[int, Cascade]], horizon: int
) -> tuple[Decimal, ...]:
    """Give the chance of a rule in every period, raised after starts of others.

    A start in period s of a rule with a cascade raises the chance in periods s + 1 to
    s + periods, cut to the horizon, to `min(1, chance * factor)`, with the largest
    factor of the windows that hold the period; overlapping windows raise it once.

    Args:
        chance (Decimal): The chance of the rule as written.
        windows (Iterable[tuple[int, Cascade]]): The start period of every disruption
            of a rule that raises this one, with the cascade of that rule.
        horizon (int): The number of periods.

    Returns:
        tuple[Decimal, ...]: The chance of periods 1 to `horizon`.

    Examples:
        >>> cascade = Cascade(rule="delays", factor=Decimal("3"), periods=1)
        >>> raised_chances(Decimal("0.1"), [(1, cascade)], horizon=3)
        (Decimal('0.1'), Decimal('0.3'), Decimal('0.1'))
    """
    factors: dict[int, Decimal] = {}
    for start, cascade in windows:
        for period in range(start + 1, min(start + cascade.periods, horizon) + 1):
            factors[period] = max(factors.get(period, Decimal(1)), cascade.factor)
    return tuple(
        min(Decimal(1), chance * factors[period]) if period in factors else chance
        for period in range(1, horizon + 1)
    )


def draw_parameter(
    value: DecimalParameter | PeriodsParameter, stream: Generator
) -> Decimal:
    """Draw one value of a parameter from its slot of a stream.

    Every slot takes exactly one uniform number; a fixed number takes its number and
    keeps its value, so a range elsewhere in the stream draws the same.

    Args:
        value (Decimal | Range[Decimal] | int | Range[int]): A fixed number or a
            range.
        stream (Generator): The stream of the parameter.

    Returns:
        Decimal: The value; a whole number of periods has no places.

    Examples:
        >>> from factory_simulator.engine.draws.streams import open_stream
        >>> draw_parameter(Range(min=2, max=2), open_stream(0, "test"))
        Decimal('2')
    """
    uniform = draw_uniform(stream)
    if isinstance(value, Decimal | int):
        return Decimal(value)
    if isinstance(value.min, int):
        return Decimal(draw_periods(cast(Range[int], value), uniform))
    return draw_value(cast(Range[Decimal], value), uniform)
