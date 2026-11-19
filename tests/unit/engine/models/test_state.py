from decimal import Decimal

from factory_simulator.engine import Observation, State, Tallies


def test_changing_a_dictionary_after_it_is_passed_to_a_state_leaves_the_state():
    stock = {"main": {"steel": Decimal(10)}}
    condition = {"press": Decimal(1)}
    measures: dict[str, dict[str, Decimal | None]] = {"cash": {"total": Decimal(5)}}
    shipped_on_time = {"order-1-1": Decimal(4)}
    state = State(
        period=1,
        cash=Decimal(5),
        stock=stock,
        condition=condition,
        customer_orders=(),
        tallies=Tallies(shipped_on_time=shipped_on_time),
        measures=measures,
    )

    stock["main"]["steel"] = Decimal(0)
    condition["press"] = Decimal(0)
    measures["cash"]["total"] = None
    shipped_on_time["order-1-1"] = Decimal(0)

    assert state.stock == {"main": {"steel": Decimal(10)}}
    assert state.condition == {"press": Decimal(1)}
    assert state.measures == {"cash": {"total": Decimal(5)}}
    assert state.tallies.shipped_on_time == {"order-1-1": Decimal(4)}


def test_changing_a_dictionary_after_it_is_passed_to_an_observation_leaves_it():
    stock = {"main": {"steel": Decimal(10)}}
    observation = Observation(
        period=1,
        horizon=2,
        finished=False,
        cash=Decimal(5),
        receivables=(),
        stock=stock,
        space={},
        lines={},
        production=(),
        plans=(),
        transfers=(),
        customer_orders=(),
        supplier_orders=(),
        disruptions=(),
        forecasts={},
        prices={},
        outcomes=(),
        events=(),
    )

    stock["main"]["steel"] = Decimal(0)

    assert observation.stock == {"main": {"steel": Decimal(10)}}
