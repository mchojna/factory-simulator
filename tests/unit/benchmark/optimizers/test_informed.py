from decimal import Decimal

from factories import hidden_and_shown_yield, plain_tiny_observation

from factory_simulator.benchmark.optimizers.informed import informed_optimizer


def test_the_informed_optimizer_plans_the_yield_its_twin_shows():
    hidden, shown = hidden_and_shown_yield()
    optimizer = informed_optimizer(lambda period, decisions: [], Decimal("1.01"), shown)

    planning = optimizer.planning_source(hidden, plain_tiny_observation())

    assert planning.lines["line-1"].items["board"].good_shares == {
        1: Decimal("0.9"),
        2: Decimal("0.9"),
        3: Decimal("0.9"),
    }


# The replacement cost of a chip is 0.5, worth 1.2 * 0.5 at the end of the window.
def test_the_informed_optimizer_at_1_2_values_a_chip_at_0_6():
    hidden, shown = hidden_and_shown_yield()
    shown["scenario"]["horizon"] = 10
    optimizer = informed_optimizer(lambda period, decisions: [], Decimal("1.2"), shown)
    observation = plain_tiny_observation() | {"horizon": 10}

    planning = optimizer.planning_source(hidden, observation)

    assert planning.terminal_values["chip"].value == Decimal("0.6")
