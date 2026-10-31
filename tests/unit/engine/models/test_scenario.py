from decimal import Decimal

from factory_simulator.engine import Disruption, Scenario, Start


def test_a_scenario_starts_with_no_cash_stock_orders_or_shapes_unless_written():
    scenario = Scenario(horizon=4)

    assert scenario.start.cash == Decimal("0.0000")
    assert dict(scenario.start.stock) == {}
    assert scenario.start.customer_orders == ()
    assert scenario.demand_shapes == scenario.disruptions == scenario.hidden == ()


def test_changing_the_dictionaries_of_a_start_after_it_is_made_leaves_it():
    stock = {"main": {"steel": Decimal(10)}}
    condition = {"press": Decimal("0.9000")}
    set_for = {"press": "bolt"}

    start = Start(stock=stock, condition=condition, set_for=set_for)
    stock["main"]["steel"] = Decimal(0)
    condition.clear()
    set_for["press"] = "nut"

    assert start.stock["main"]["steel"] == Decimal(10)
    assert dict(start.condition) == {"press": Decimal("0.9000")}
    assert dict(start.set_for) == {"press": "bolt"}


def test_a_disruption_gives_the_agent_no_notice_unless_written():
    cut = Disruption(
        id="disruption-1",
        kind="capacity_cut",
        target=("press",),
        start=2,
        duration=3,
        effect=Decimal("0.25"),
    )

    assert cut.notice == 0
