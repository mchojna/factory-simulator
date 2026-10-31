from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    example_count,
    hidden_and_shown_yield,
    plain_tiny_description,
    plain_tiny_observation,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.benchmark.models.inputs import Arrival, TerminalValue, Tier
from factory_simulator.benchmark.program.decisions import PlanningSource
from factory_simulator.benchmark.program.expected_source import (
    Demand,
    Window,
    add_demand_samples,
    customer_product_demand,
    expected_planning_input,
    expected_planning_source,
    expected_supplier_orders,
    informed_planning_source,
    longest_chain,
    shape_factor,
)

LEAN = Decimal("1.01")

# A hidden demand of a season of 10 periods at the factor 0.0001, then 10 at 1.
LOW_SEASON = {
    "kind": "season",
    "target": "all",
    "factors": [Decimal("0.0001"), Decimal(1)],
    "period_length": 10,
}

# An observation without disruptions.
NO_DISRUPTIONS: dict[str, Any] = {"disruptions": []}

# Observed quantities of up to 20 of the periods 1 to 30.
observed_quantities = st.dictionaries(
    st.integers(min_value=1, max_value=30),
    st.decimals(min_value=0, max_value=1000, places=3),
    min_size=1,
    max_size=20,
)

# Factors from 0.0001 to 10.
positive_factors = st.decimals(min_value=Decimal("0.0001"), max_value=10, places=4)


def orders_of(
    description: dict[str, Any], observation: dict[str, Any], demand: Demand
) -> list[tuple[str, int, Decimal]]:
    planning = expected_planning_input(
        observation, "horizon", demand, LEAN, {}, description
    )
    return [
        (order.id, order.arrival, order.open_quantity)
        for order in planning.customer_orders
    ]


# An expected world of the chip of the plain tiny factory over 8 periods.
def chip_world(
    completeness: Decimal, disruptions: list[dict[str, Any]]
) -> dict[str, Any]:
    delivery = {
        "punctual": True,
        "delay": 0,
        "completeness": completeness,
        "acceptance": Decimal(1),
    }
    path = "suppliers.chip-maker.catalogue.chip.backfill_delay"
    return {
        "parameters": {path: {"value": 2}},
        "deliveries": {"chip-maker/chip": [delivery] * 8},
        "disruptions": disruptions,
    }


# The observation of period 2 with an order of 100 chips placed in period 1.
def chip_order_seen(open_quantity: int) -> dict[str, Any]:
    order = {
        "id": "buy-1-1",
        "supplier": "chip-maker",
        "material": "chip",
        "warehouse": "main",
        "quantity": 100,
        "open_quantity": open_quantity,
        "unit_price": Decimal("0.5"),
        "express": False,
        "placed": 1,
        "expected_arrival": 2,
    }
    return {"period": 2, "horizon": 8, "supplier_orders": [order]}


def test_expected_demand_adds_an_order_of_the_mean_in_every_coming_period():
    orders = orders_of(plain_tiny_description(), plain_tiny_observation(), "expected")

    assert orders == [
        ("order-1-1", 1, Decimal(4)),
        ("expected-2-1", 2, Decimal(4)),
        ("expected-3-1", 3, Decimal(4)),
    ]


def test_the_order_book_gives_only_the_open_order():
    orders = orders_of(plain_tiny_description(), plain_tiny_observation(), "order_book")

    assert orders == [("order-1-1", 1, Decimal(4))]


def test_a_forecast_replaces_the_mean_of_its_period():
    observation = plain_tiny_observation()
    observation["forecasts"] = {
        "distributor/monitor": [{"period": 2, "quantity": Decimal(6)}]
    }

    orders = orders_of(plain_tiny_description(), observation, "expected")

    assert orders == [
        ("order-1-1", 1, Decimal(4)),
        ("expected-2-1", 2, Decimal(6)),
        ("expected-3-1", 3, Decimal(4)),
    ]


def test_a_season_factor_of_1_5_gives_an_order_of_6():
    description = plain_tiny_description()
    season = {
        "kind": "season",
        "target": "all",
        "factors": [Decimal(1), Decimal("1.5"), Decimal(1)],
        "period_length": 1,
    }
    description["scenario"]["demand_shapes"] = [season]

    orders = orders_of(description, plain_tiny_observation(), "expected")

    assert orders == [
        ("order-1-1", 1, Decimal(4)),
        ("expected-2-1", 2, Decimal(6)),
        ("expected-3-1", 3, Decimal(4)),
    ]


# In period 1, 99 periods before its middle, the exponent of an s-curve of steepness
# 100000 is exp(9900000), beyond the largest number of a decimal context: it is
# Infinity, as in the engine, and the factor is `from_factor`.
def test_an_s_curve_far_before_its_middle_gives_its_from_factor():
    s_curve = {
        "kind": "s_curve",
        "target": "all",
        "middle": 100,
        "steepness": Decimal(100000),
        "from_factor": Decimal("0.5"),
        "to_factor": Decimal(2),
    }

    assert shape_factor(s_curve, 1) == Decimal("0.5")


# The orders of 4 and then 8 give a base demand of 4; the window of period 3 ends in
# period 7, so periods 8 to 10 expect 4 * 2 monitors each, 24 in all.
def test_hidden_demand_removes_the_past_step_before_predicting_future_orders():
    description = plain_tiny_description()
    del description["manifest"]["customers"]["distributor"]["products"]["monitor"][
        "demand"
    ]
    description["scenario"]["demand_shapes"] = [
        {"kind": "step", "target": "all", "period": 2, "factor": Decimal(2)}
    ]
    source = expected_planning_source("lead_chain", "expected", LEAN)
    planning = None
    for period, quantity in ((1, 4), (2, 8), (3, 8)):
        observation = plain_tiny_observation()
        observation["period"] = period
        observation["horizon"] = 10
        observation["customer_orders"] = [
            {
                "id": f"order-{period}-1",
                "customer": "distributor",
                "product": "monitor",
                "quantity": Decimal(quantity),
                "shipped": Decimal(0),
                "arrival": period,
                "due": period,
                "last": period,
            }
        ]
        planning = source(description, observation)

    assert planning is not None
    expected = next(order for order in planning.customer_orders if order.arrival == 4)
    assert expected.open_quantity == Decimal(8)
    assert planning.terminal_values["monitor"].expected_use == Decimal(24)


def test_hidden_demand_removes_a_step_active_from_the_first_period():
    description = plain_tiny_description()
    del description["manifest"]["customers"]["distributor"]["products"]["monitor"][
        "demand"
    ]
    description["scenario"]["demand_shapes"] = [
        {"kind": "step", "target": "all", "period": 1, "factor": Decimal("1.5")}
    ]
    observation = plain_tiny_observation()
    observation["customer_orders"][0]["quantity"] = Decimal(6)

    planning = expected_planning_source("horizon", "expected", LEAN)(
        description, observation
    )

    expected = next(order for order in planning.customer_orders if order.arrival == 2)
    assert expected.open_quantity == Decimal(6)


def test_hidden_demand_removes_a_visible_shock_from_an_observed_order():
    description = plain_tiny_description()
    del description["manifest"]["customers"]["distributor"]["products"]["monitor"][
        "demand"
    ]
    observation = plain_tiny_observation()
    observation["customer_orders"][0]["quantity"] = Decimal(8)
    observation["disruptions"] = [
        {
            "kind": "demand_shock",
            "target": ["monitor"],
            "start": 1,
            "duration": 1,
            "factor": Decimal(2),
        }
    ]

    planning = expected_planning_source("horizon", "expected", LEAN)(
        description, observation
    )

    expected = next(order for order in planning.customer_orders if order.arrival == 2)
    assert expected.open_quantity == Decimal(4)


# The plain tiny description with hidden demand and the demand shapes given.
def hidden_demand_description(shapes: list[dict[str, Any]]) -> dict[str, Any]:
    description = plain_tiny_description()
    del description["manifest"]["customers"]["distributor"]["products"]["monitor"][
        "demand"
    ]
    description["scenario"]["demand_shapes"] = shapes
    return description


# The observation of a period of horizon 20 with the customer orders given, each a
# pair of its arrival and quantity.
def observation_with_orders(
    period: int, orders: list[tuple[int, Decimal]]
) -> dict[str, Any]:
    observation = plain_tiny_observation() | {"period": period, "horizon": 20}
    observation["customer_orders"] = [
        {
            "id": f"order-{arrival}-1",
            "customer": "distributor",
            "product": "monitor",
            "quantity": quantity,
            "shipped": Decimal(0),
            "arrival": arrival,
            "due": max(arrival, 1),
            "last": max(arrival, 1),
        }
        for arrival, quantity in orders
    ]
    return observation


# The quantity of the expected order of a period after the source sees the
# observations given, with the window `lead_chain`.
def expected_in_period(
    period: int, description: dict[str, Any], observations: list[dict[str, Any]]
) -> Decimal:
    source = expected_planning_source("lead_chain", "expected", LEAN)
    planning = None
    for observation in observations:
        planning = source(description, observation)
    assert planning is not None
    return next(
        order.open_quantity
        for order in planning.customer_orders
        if order.id.startswith(f"expected-{period}-")
    )


# The ten periods of the low season, an order of 0.001 in periods 1, 2, 4 and 7 and
# none in the six others, divided by its factor 0.0001, give 10, 10, 0, 10, 0, 0, 10, 0,
# 0, 0: a mean of 40 / 10 = 4, times the factor 1 of period 11.
def test_hidden_demand_counts_a_period_without_an_order_as_0():
    observations = [
        observation_with_orders(
            period, [(period, Decimal("0.001"))] if period in (1, 2, 4, 7) else []
        )
        for period in range(1, 11)
    ]

    quantity = expected_in_period(
        11, hidden_demand_description([LOW_SEASON]), observations
    )

    assert quantity == Decimal("4.000")


# The demand samples of the observations of the periods given, each with its order of
# the quantity given, none for 0, under a step of a factor from period 1.
def samples_of(
    quantities: dict[int, Decimal], factor: Decimal
) -> tuple[dict[str, dict[int, Decimal]], dict[str, Any]]:
    step = {"kind": "step", "target": "all", "period": 1, "factor": factor}
    description = hidden_demand_description([step])
    demand_samples: dict[str, dict[int, Decimal]] = {}
    for period, quantity in quantities.items():
        orders = [(period, quantity)] if quantity > 0 else []
        observation = observation_with_orders(period, orders)
        add_demand_samples(demand_samples, observation, description, NO_DISRUPTIONS)
    return demand_samples, description


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(observed_quantities, positive_factors, st.integers(min_value=31, max_value=40))
def test_an_observed_period_without_an_order_never_raises_the_base_demand(
    quantities: dict[int, Decimal], factor: Decimal, empty_period: int
):
    terms: dict[str, Any] = {}
    demand_samples, description = samples_of(quantities, factor)
    before = customer_product_demand("distributor", "monitor", demand_samples, terms)

    observation = observation_with_orders(empty_period, [])
    add_demand_samples(demand_samples, observation, description, NO_DISRUPTIONS)

    assert (
        customer_product_demand("distributor", "monitor", demand_samples, terms)
        <= before
    )
    assert len(demand_samples["distributor/monitor"]) == len(quantities) + 1


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(observed_quantities, positive_factors, st.data())
def test_a_repeated_observation_leaves_the_demand_samples_unchanged(
    quantities: dict[int, Decimal], factor: Decimal, data: st.DataObject
):
    demand_samples, description = samples_of(quantities, factor)
    seen = {pair: dict(samples) for pair, samples in demand_samples.items()}
    period = data.draw(st.sampled_from(sorted(quantities)))
    orders = [(period, quantities[period])] if quantities[period] > 0 else []

    observation = observation_with_orders(period, orders)
    add_demand_samples(demand_samples, observation, description, NO_DISRUPTIONS)

    assert demand_samples == seen
    assert len(demand_samples["distributor/monitor"]) == len(quantities)


# A starting order of 50 arrived in period 0 and is no sample; the order of 4 in period
# 1 is the one sample, so period 2 expects 4.
def test_a_starting_order_gives_no_demand_sample():
    observation = observation_with_orders(1, [(0, Decimal(50)), (1, Decimal(4))])

    quantity = expected_in_period(2, hidden_demand_description([]), [observation])

    assert quantity == Decimal("4.000")


# The source sees periods 1, 2 and 5 only: 6, 0 and 6, a mean of 4. The order of 9 of
# period 3, still open in period 5, and the unseen periods 3 and 4 give no sample.
def test_only_the_periods_of_the_observations_give_demand_samples():
    observations = [
        observation_with_orders(1, [(1, Decimal(6))]),
        observation_with_orders(2, []),
        observation_with_orders(5, [(3, Decimal(9)), (5, Decimal(6))]),
    ]

    quantity = expected_in_period(6, hidden_demand_description([]), observations)

    assert quantity == Decimal("4.000")


# With the step of factor 2 from period 2, periods 1 to 3 order 4, nothing and 8: the
# samples 4, 0 and 4 have the mean 8 / 3, and period 4 expects 16 / 3, 5.333.
def test_hidden_demand_divides_out_a_step_and_counts_a_period_without_an_order():
    step = {"kind": "step", "target": "all", "period": 2, "factor": Decimal(2)}
    observations = [
        observation_with_orders(1, [(1, Decimal(4))]),
        observation_with_orders(2, []),
        observation_with_orders(3, [(3, Decimal(8))]),
    ]

    quantity = expected_in_period(4, hidden_demand_description([step]), observations)

    assert quantity == Decimal("5.333")


# A visible shock of factor 2 in period 1 turns its order of 8 into the sample 4;
# period 2 has no order, the sample 0; period 3 expects the mean 2.
def test_hidden_demand_divides_out_a_shock_and_counts_a_period_without_an_order():
    shock = {
        "kind": "demand_shock",
        "target": ["monitor"],
        "start": 1,
        "duration": 1,
        "factor": Decimal(2),
    }
    observations = [
        observation_with_orders(1, [(1, Decimal(8))]) | {"disruptions": [shock]},
        observation_with_orders(2, []) | {"disruptions": [shock]},
    ]

    quantity = expected_in_period(3, hidden_demand_description([]), observations)

    assert quantity == Decimal("2.000")


def test_a_hidden_punctuality_and_yield_give_arrival_at_the_lead_time_and_yield_one():
    description = plain_tiny_description()
    manifest = description["manifest"]
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["punctuality"]
    entry["lead_time"] = 2
    for line_item in manifest["lines"]["line-1"]["items"].values():
        del line_item["yield"]
    description["scenario"]["hidden"] = [
        "suppliers.catalogue.punctuality",
        "lines.items.yield",
    ]

    planning = expected_planning_input(
        plain_tiny_observation(), "horizon", "expected", LEAN, {}, description
    )

    first = planning.buy_options[0]
    assert (first.period, first.arrivals) == (
        1,
        (Arrival(period=3, accepted=Decimal(1), left_open=Decimal(0)),),
    )
    line_items = planning.lines["line-1"].items.values()
    assert [line_item.good_shares for line_item in line_items] == [
        {1: Decimal(1), 2: Decimal(1), 3: Decimal(1)}
    ] * 2


def board_shares(
    source: PlanningSource, description: dict[str, Any]
) -> Mapping[int, Decimal]:
    planning = source(description, plain_tiny_observation())
    return planning.lines["line-1"].items["board"].good_shares


def test_the_informed_source_plans_a_hidden_yield_at_the_cut_mean_its_twin_shows():
    hidden, shown = hidden_and_shown_yield()

    limited = board_shares(
        expected_planning_source("lead_chain", "expected", LEAN), hidden
    )
    informed = board_shares(informed_planning_source(LEAN, shown), hidden)

    assert limited == {1: Decimal(1), 2: Decimal(1), 3: Decimal(1)}
    assert informed == {1: Decimal("0.9"), 2: Decimal("0.9"), 3: Decimal("0.9")}


def test_a_visible_outage_of_0_5_halves_the_accepted_share_of_a_buy_arriving_in_it():
    observation = plain_tiny_observation()
    outage = {
        "id": "disruption-1",
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": 2,
        "duration": 1,
        "strength": Decimal("0.5"),
    }
    observation["disruptions"] = [outage]

    planning = expected_planning_input(
        observation, "horizon", "expected", LEAN, {}, plain_tiny_description()
    )

    arrivals = [option.arrivals for option in planning.buy_options]
    assert arrivals == [
        (Arrival(period=2, accepted=Decimal("0.5"), left_open=Decimal(0)),),
        (Arrival(period=3, accepted=Decimal(1), left_open=Decimal(0)),),
        (),
    ]


def test_a_price_drawn_every_period_plans_the_seen_price_now_and_the_mean_later():
    description = plain_tiny_description()
    entry = description["manifest"]["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["price"] = {
        "min": Decimal("0.4"),
        "max": Decimal("0.6"),
        "distribution": "uniform",
        "drawn": "period",
        "cut_mean": Decimal("0.5"),
    }
    observation = plain_tiny_observation()
    observation["prices"] = {"chip-maker": {"chip": Decimal("0.4300")}}

    planning = expected_planning_input(
        observation, "horizon", "expected", LEAN, {}, description
    )

    assert [(option.period, option.unit_price) for option in planning.buy_options] == [
        (1, Decimal("0.4300")),
        (2, Decimal("0.5000")),
        (3, Decimal("0.5000")),
    ]


# A chip costs 0.5, a board 2 * 0.5 + 1 = 2 and a monitor 2 * 2 + 2 = 6, each worth
# 1.01 times its cost. A chip bought in one period arrives in the next, becomes a board
# in that period and a monitor in the one after, which ships in the period after that,
# so the longest chain is 3: the window ends in period 5 and the demand of 4 monitors,
# 8 boards and 16 chips a period counts in periods 6 to 8.
def test_the_terminal_value_of_the_plain_tiny_factory():
    observation = plain_tiny_observation() | {"horizon": 10}

    planning = expected_planning_input(
        observation, "lead_chain", "expected", LEAN, {}, plain_tiny_description()
    )

    assert planning.terminal_values == {
        "chip": TerminalValue(value=Decimal("0.505"), expected_use=Decimal(48)),
        "board": TerminalValue(value=Decimal("2.02"), expected_use=Decimal(24)),
        "monitor": TerminalValue(value=Decimal("6.06"), expected_use=Decimal(12)),
    }


# At the buffered factor each item is worth 1.2 times its cost: chip 1.2 * 0.5, board
# 1.2 * 2 and monitor 1.2 * 6, with the expected uses of the lean factor.
def test_the_buffered_factor_values_the_plain_tiny_factory_at_1_2_times_its_cost():
    observation = plain_tiny_observation() | {"horizon": 10}

    planning = expected_planning_input(
        observation,
        "lead_chain",
        "expected",
        Decimal("1.2"),
        {},
        plain_tiny_description(),
    )

    assert planning.terminal_values == {
        "chip": TerminalValue(value=Decimal("0.6"), expected_use=Decimal(48)),
        "board": TerminalValue(value=Decimal("2.4"), expected_use=Decimal(24)),
        "monitor": TerminalValue(value=Decimal("7.2"), expected_use=Decimal(12)),
    }


# The expected use of each item at the end of the window of period 1, which ends in
# period 5, on a horizon and with the demand shapes and disruptions given.
def terminal_uses(
    horizon: int,
    shapes: list[dict[str, Any]],
    disruptions: list[dict[str, Any]] | None = None,
) -> dict[str, Decimal]:
    description = plain_tiny_description()
    description["scenario"]["demand_shapes"] = shapes
    observation = plain_tiny_observation() | {"horizon": horizon}
    observation["disruptions"] = disruptions or []

    planning = expected_planning_input(
        observation, "lead_chain", "expected", LEAN, {}, description
    )

    return {
        item_id: terminal.expected_use
        for item_id, terminal in planning.terminal_values.items()
    }


# Demand of 4 monitors ends in period 2, so periods 6 to 8 after the window expect no
# monitor, and no board or chip for one.
def test_demand_withdrawn_before_the_window_ends_gives_no_expected_use():
    withdrawal = {"kind": "step", "target": "all", "period": 2, "factor": Decimal(0)}

    uses = terminal_uses(20, [withdrawal])

    assert uses == {"chip": Decimal(0), "board": Decimal(0), "monitor": Decimal(0)}


# The expected uses of a window of the plain tiny factory whose demand, seen or hidden
# and learned from one period, ends in a period.
def withdrawn_uses(
    demand: int, hidden: bool, withdrawn: int, period: int, window: Window, horizon: int
) -> dict[str, Decimal]:
    description = plain_tiny_description()
    terms = description["manifest"]["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = demand
    demand_samples: dict[str, dict[int, Decimal]] = {}
    if hidden:
        del terms["demand"]
        demand_samples["distributor/monitor"] = {1: Decimal(demand)}
    description["scenario"]["demand_shapes"] = [
        {"kind": "step", "target": "all", "period": withdrawn, "factor": Decimal(0)}
    ]
    observation = plain_tiny_observation() | {"period": period, "horizon": horizon}

    planning = expected_planning_input(
        observation, window, "expected", LEAN, demand_samples, description
    )

    return {
        item_id: terminal.expected_use
        for item_id, terminal in planning.terminal_values.items()
    }


# Demand ends by the period after the observation, so no period after any window
# expects an order.
@st.composite
def withdrawals(draw: st.DrawFn) -> tuple[int, bool, int, int, Window, int]:
    period = draw(st.integers(min_value=1, max_value=30))
    withdrawn = draw(st.integers(min_value=2, max_value=period + 1))
    window = draw(st.sampled_from(cast(list[Window], ["lead_chain", "myopic"])))
    horizon = draw(st.integers(min_value=period + 1, max_value=40))
    demand = draw(st.integers(min_value=1, max_value=1000))
    return demand, draw(st.booleans()), withdrawn, period, window, horizon


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(withdrawals())
def test_a_known_future_demand_of_0_gives_no_expected_use(
    case: tuple[int, bool, int, int, Window, int],
):
    uses = withdrawn_uses(*case)

    assert sum(uses.values(), Decimal(0)) == 0


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(withdrawals(), st.integers(min_value=1, max_value=40))
def test_a_longer_horizon_of_demand_0_adds_no_expected_use(
    case: tuple[int, bool, int, int, Window, int], extra: int
):
    demand, hidden, withdrawn, period, window, horizon = case

    uses = withdrawn_uses(demand, hidden, withdrawn, period, window, horizon + extra)

    assert all(use == 0 for use in uses.values())


# Demand of 4 monitors ends in period 7: only period 6 of periods 6 to 8 expects 4.
def test_demand_withdrawn_after_the_window_counts_only_the_periods_before_it():
    withdrawal = {"kind": "step", "target": "all", "period": 7, "factor": Decimal(0)}

    uses = terminal_uses(20, [withdrawal])

    assert uses == {"chip": Decimal(16), "board": Decimal(8), "monitor": Decimal(4)}


# Demand doubles from period 7: 4 + 8 + 8 monitors in periods 6 to 8.
def test_a_step_increase_after_the_window_raises_the_expected_use():
    step = {"kind": "step", "target": "all", "period": 7, "factor": Decimal(2)}

    uses = terminal_uses(20, [step])

    assert uses == {"chip": Decimal(80), "board": Decimal(40), "monitor": Decimal(20)}


# Seasons of 3 periods at factors 1 and 0.5: period 6 is in the second season, 7 and
# 8 in the third, so 2 + 4 + 4 monitors.
def test_a_season_after_the_window_counts_the_factor_of_each_period():
    season = {
        "kind": "season",
        "target": "all",
        "factors": [Decimal(1), Decimal("0.5")],
        "period_length": 3,
    }

    uses = terminal_uses(20, [season])

    assert uses == {"chip": Decimal(40), "board": Decimal(20), "monitor": Decimal(10)}


# A visible shock halves the demand of period 7: 4 + 2 + 4 monitors.
def test_a_visible_demand_shock_after_the_window_counts_in_its_period():
    shock = {
        "id": "disruption-1",
        "kind": "demand_shock",
        "target": ["monitor"],
        "start": 7,
        "duration": 1,
        "factor": Decimal("0.5"),
    }

    uses = terminal_uses(20, [], [shock])

    assert uses == {"chip": Decimal(40), "board": Decimal(20), "monitor": Decimal(10)}


# The horizon of 7 leaves 2 periods after the window, fewer than the chain of 3.
def test_a_horizon_closer_than_the_chain_counts_only_the_periods_left():
    uses = terminal_uses(7, [])

    assert uses == {"chip": Decimal(32), "board": Decimal(16), "monitor": Decimal(8)}


# A chip bought in one period arrives in the next, becomes a board in that period and
# a monitor in the one after, which ships in the period after that: the longest chain
# is 3 and the window 3 + 2.
def test_the_window_of_the_plain_tiny_factory_is_its_longest_chain_plus_2():
    observation = plain_tiny_observation() | {"horizon": 10}

    planning = expected_planning_input(
        observation, "lead_chain", "expected", LEAN, {}, plain_tiny_description()
    )

    assert (planning.window_end, planning.horizon) == (5, 10)


# The window of 3 + 2 periods from period 1 is cut at the horizon of 3.
def test_the_window_of_the_plain_tiny_factory_is_cut_at_its_horizon():
    planning = expected_planning_input(
        plain_tiny_observation(),
        "lead_chain",
        "expected",
        LEAN,
        {},
        plain_tiny_description(),
    )

    assert (planning.window_end, planning.horizon) == (3, 3)


def test_a_myopic_window_ends_at_the_period_of_the_observation():
    planning = expected_planning_input(
        plain_tiny_observation(),
        "myopic",
        "expected",
        LEAN,
        {},
        plain_tiny_description(),
    )

    assert (planning.window_end, planning.horizon) == (1, 3)


def test_a_planning_source_gives_the_planning_input_of_its_window():
    source = expected_planning_source("lead_chain", "order_book", LEAN)

    planning = source(plain_tiny_description(), plain_tiny_observation())

    assert planning.window_end == 3


def test_a_window_of_the_whole_horizon_ends_at_the_horizon():
    observation = plain_tiny_observation() | {"horizon": 10}

    planning = expected_planning_input(
        observation, "horizon", "expected", LEAN, {}, plain_tiny_description()
    )

    assert (planning.window_end, planning.horizon, planning.terminal_values) == (
        10,
        10,
        {},
    )


def test_a_range_counts_at_the_cut_mean_the_description_gives():
    demand = {
        "distribution": "lognormal",
        "min": 14,
        "max": 70,
        "median": 35,
        "spread": "0.4",
        "cut_mean": "36.222159",
    }

    assert customer_product_demand("c", "p", {}, {"demand": demand}) == Decimal(
        "36.222159"
    )


# The monitor takes 1 period on line a and 2 on line b; its alternative recipe uses a
# chip with a lead time of 4, so the longest chain is 4 + 2.
def test_the_longest_chain_counts_every_line_and_every_recipe():
    parameters = {
        "suppliers.s.catalogue.chip.lead_time": {"value": 1},
        "suppliers.s.catalogue.slow-chip.lead_time": {"value": 4},
        "lines.a.items.monitor.lead_time": {"value": 1},
        "lines.b.items.monitor.lead_time": {"value": 2},
    }
    monitor = {
        "default_recipe": "standard",
        "recipes": {"standard": {"chip": 1}, "alternative": {"slow-chip": 1}},
    }
    manifest: dict[str, Any] = {
        "materials": {"chip": {}, "slow-chip": {}},
        "components": {},
        "products": {"monitor": monitor},
        "suppliers": {"s": {"catalogue": {"chip": {}, "slow-chip": {}}}},
        "lines": {"a": {"items": {"monitor": {}}}, "b": {"items": {"monitor": {}}}},
    }

    assert longest_chain({"parameters": parameters}, manifest) == 6


def test_a_minimum_and_a_discount_tier_reach_the_buy_options_at_their_means():
    description = plain_tiny_description()
    entry = description["manifest"]["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["min_quantity"] = Decimal(10)
    entry["discounts"] = [
        {
            "from": Decimal(100),
            "price": {
                "min": Decimal("0.3"),
                "max": Decimal("0.4"),
                "cut_mean": Decimal("0.35"),
            },
        }
    ]

    planning = expected_planning_input(
        plain_tiny_observation(), "horizon", "expected", LEAN, {}, description
    )

    option = planning.buy_options[0]
    assert option.min_quantity == Decimal(10)
    assert option.tiers == (Tier(from_=Decimal("100.000"), unit_price=Decimal("0.35")),)


# The 20 chips left open by the first delivery arrive 2 + 2 periods after the order
# is placed, all accepted: 20 * 1 * 1.
def test_an_order_after_its_first_delivery_waits_for_its_backfill():
    world = chip_world(Decimal("0.8"), [])

    orders = expected_supplier_orders(chip_order_seen(20), 8, world, {"buy-1-1": 2})

    assert orders[0].arrivals == (
        Arrival(period=4, accepted=Decimal("20.000"), left_open=Decimal(0)),
    )


def test_a_late_first_delivery_dates_its_backfill_from_the_delivered_period():
    world = chip_world(Decimal("0.8"), [])
    observation = chip_order_seen(20)
    observation["period"] = 4

    orders = expected_supplier_orders(observation, 8, world, {"buy-1-1": 4})

    assert orders[0].arrivals == (
        Arrival(period=6, accepted=Decimal("20.000"), left_open=Decimal(0)),
    )


def test_a_partial_cancellation_does_not_turn_an_order_into_a_backfill():
    world = chip_world(Decimal("0.8"), [])
    observation = chip_order_seen(20)
    observation["period"] = 1

    orders = expected_supplier_orders(observation, 8, world)

    assert orders[0].arrivals == (
        Arrival(period=2, accepted=Decimal("16.000"), left_open=Decimal(4)),
        Arrival(period=4, accepted=Decimal("4.000"), left_open=Decimal(0)),
    )


def test_an_open_order_keeps_the_missing_part_for_its_backfill():
    world = chip_world(Decimal("0.8"), [])
    observation = chip_order_seen(100)
    observation["supplier_orders"][0]["expected_arrival"] = 3

    orders = expected_supplier_orders(observation, 8, world)

    assert orders[0].arrivals == (
        Arrival(period=3, accepted=Decimal("80.000"), left_open=Decimal("20.000")),
        Arrival(period=5, accepted=Decimal("20.000"), left_open=Decimal(0)),
    )


def test_a_first_delivery_event_marks_only_its_order_as_a_backfill():
    description = plain_tiny_description()
    entry = description["manifest"]["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["completeness"] = Decimal("0.8")
    entry["backfill_delay"] = 2
    source = expected_planning_source("horizon", "expected", LEAN)
    observation = plain_tiny_observation()
    observation["horizon"] = 8
    observation["period"] = 2
    first = chip_order_seen(20)["supplier_orders"][0]
    second = first | {"id": "buy-1-2"}
    observation["supplier_orders"] = [first, second]
    observation["events"] = [
        {"kind": "delivery", "reference": "buy-1-1", "backfill": False}
    ]

    planning = source(description, observation)

    assert planning.state.supplier_orders[0].arrivals[0].period == 4
    assert planning.state.supplier_orders[1].arrivals[0].period == 3


def test_a_visible_transport_delay_moves_the_arrival_of_an_open_order():
    delay = {
        "kind": "transport_delay",
        "target": ["chip-maker"],
        "start": 1,
        "duration": 8,
        "delay": 2,
    }
    world = chip_world(Decimal(1), [delay])

    orders = expected_supplier_orders(chip_order_seen(100), 8, world)

    # 2 + 2.
    assert orders[0].arrivals == (
        Arrival(period=4, accepted=Decimal("100.000"), left_open=Decimal(0)),
    )


def test_a_window_of_a_number_of_periods_is_refused():
    with pytest.raises(
        ValueError, match="window: 0 is not horizon, lead_chain or myopic"
    ):
        expected_planning_source(cast(Window, 0), "expected", LEAN)


def test_a_window_named_weekly_is_refused():
    with pytest.raises(
        ValueError, match="window: weekly is not horizon, lead_chain or myopic"
    ):
        expected_planning_source(cast(Window, "weekly"), "expected", LEAN)


def test_a_demand_other_than_expected_or_order_book_is_refused():
    with pytest.raises(ValueError, match="demand: mean is not expected or order_book"):
        expected_planning_source("horizon", cast(Demand, "mean"), LEAN)
