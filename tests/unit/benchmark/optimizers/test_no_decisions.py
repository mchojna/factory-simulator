from factories import plain_tiny_description, plain_tiny_observation

from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


def test_no_decisions_gives_no_decision_in_the_first_period_of_the_plain_tiny_run():
    decisions = no_decisions(plain_tiny_description(), plain_tiny_observation())

    assert decisions == []
