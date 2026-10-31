from decimal import Decimal

from factories import tiered_chip_world

from factory_simulator.engine import (
    Cash,
    Factory,
    Line,
    Range,
    Scenario,
    World,
    build_description,
)

ZERO = Decimal(0)


def test_the_description_shows_the_drawn_price_of_a_tier_written_as_a_range():
    tiers = [{"from": "1000.000", "price": {"min": "4.0000", "max": "4.5000"}}]
    world = tiered_chip_world(discounts=tiers)

    [tier] = (
        build_description(world)
        .factory.suppliers["chip-maker"]
        .catalogue["chip"]
        .discounts
    )

    drawn = world.parameters[
        "suppliers.chip-maker.catalogue.chip.discounts.1000.000.price"
    ]
    assert type(tier.price) is Decimal
    assert tier.price == drawn
    assert Decimal("4.0000") <= tier.price <= Decimal("4.5000")


def test_the_description_keeps_the_range_of_a_parameter_a_scenario_may_hide():
    press = Line(
        capacity=Range(min=Decimal(30), max=Decimal(50)),
        wear_per_period=ZERO,
        wear_per_hour=ZERO,
        breakdown_chance=Range(min=Decimal("0.0100"), max=Decimal("0.0300")),
        breakdown_loss=ZERO,
        repair_cost=ZERO,
        repair_time=ZERO,
        repair_limit=ZERO,
        items={},
    )
    cash = Cash(
        credit_limit=ZERO,
        credit_interest=ZERO,
        debit_interest=ZERO,
        overdraft_interest=ZERO,
    )
    factory = Factory(
        materials={},
        components={},
        products={},
        suppliers={},
        customers={},
        lines={"press": press},
        warehouses={},
        cash=cash,
    )
    world = World(
        factory=factory,
        scenario=Scenario(horizon=4),
        parameters={
            "lines.press.capacity": Decimal(40),
            "lines.press.breakdown_chance": Decimal("0.0200"),
        },
        drawn=frozenset(),
        demand={},
        deliveries={},
        yields={},
        breakdowns={},
    )

    line = build_description(world).factory.lines["press"]

    # The capacity may not be hidden and shows its drawn value; the breakdown chance
    # may be hidden and shows its range.
    assert line.capacity == Decimal(40)
    assert line.breakdown_chance == Range(min=Decimal("0.0100"), max=Decimal("0.0300"))
