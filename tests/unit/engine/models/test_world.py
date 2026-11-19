from decimal import Decimal

from factory_simulator.engine import Cash, Factory, Scenario, World

ZERO = Decimal(0)


def test_changing_a_dictionary_after_it_is_passed_to_a_world_leaves_the_world():
    factory = Factory(
        materials={},
        components={},
        products={},
        suppliers={},
        customers={},
        lines={},
        warehouses={},
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
    )
    parameters = {"lines.press.capacity": Decimal(40)}
    demand = {"shop/bolt": (Decimal(10), Decimal(12))}
    forecasts = {"shop/bolt": ((Decimal(11),), (None,))}
    world = World(
        factory=factory,
        scenario=Scenario(horizon=2),
        parameters=parameters,
        drawn=frozenset(),
        demand=demand,
        deliveries={},
        yields={},
        breakdowns={},
        forecasts=forecasts,
    )

    parameters["lines.press.capacity"] = Decimal(0)
    demand["shop/bolt"] = (Decimal(0), Decimal(0))
    forecasts.clear()

    assert world.parameters == {"lines.press.capacity": Decimal(40)}
    assert world.demand == {"shop/bolt": (Decimal(10), Decimal(12))}
    assert world.forecasts == {"shop/bolt": ((Decimal(11),), (None,))}
