from factory_simulator.engine import Decisions


def test_a_period_without_decisions_holds_none():
    assert Decisions(period=3).decisions == ()
