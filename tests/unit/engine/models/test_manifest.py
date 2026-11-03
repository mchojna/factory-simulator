import operator
from decimal import Decimal

import pytest

from factory_simulator.engine import (
    Cash,
    Customer,
    CustomerProduct,
    Factory,
    Line,
    LineItem,
    MadeItem,
    Range,
)
from factory_simulator.engine.models.manifest import read_only_copy

ZERO = Decimal(0)
ONE = Decimal(1)


def test_a_read_only_copy_keeps_its_nested_values_when_the_mapping_changes():
    stock = {"main": {"steel": Decimal(10)}}

    copied = read_only_copy(stock)
    stock["main"]["steel"] = ZERO
    stock["spare"] = {}

    assert dict(copied) == {"main": {"steel": Decimal(10)}}
    with pytest.raises(TypeError):
        operator.setitem(copied["main"], "steel", ZERO)


def test_a_range_is_uniform_and_drawn_once_per_run_unless_written_otherwise():
    written = Range(min=Decimal("0.8000"), max=Decimal("0.9200"))

    assert (written.distribution, written.drawn) == ("uniform", "run")


def test_changing_the_dictionaries_of_a_factory_after_it_is_made_leaves_it():
    recipe = {"steel": ONE}
    items = {"bolt": LineItem(time=ONE, cost=ONE, yield_=ONE)}
    terms = CustomerProduct(
        price=Decimal(5),
        transport_cost=ZERO,
        demand=Decimal(10),
        lead_time=1,
        patience=1,
        late_penalty=ZERO,
        lost_sale_penalty=ZERO,
    )
    bought = {"bolt": terms}
    lines = {
        "press": Line(
            capacity=Decimal(40),
            wear_per_period=ZERO,
            wear_per_hour=ZERO,
            breakdown_chance=ZERO,
            breakdown_loss=ZERO,
            repair_cost=ZERO,
            repair_time=ZERO,
            repair_limit=ONE,
            items=items,
        )
    }
    factory = Factory(
        materials={},
        components={
            "board": MadeItem(
                space=ONE,
                storage_cost=ZERO,
                salvage_value=ZERO,
                recipes={"standard": recipe},
            )
        },
        products={},
        suppliers={},
        customers={"shop": Customer(products=bought)},
        lines=lines,
        warehouses={},
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
    )

    recipe["steel"] = Decimal(2)
    items.clear()
    bought.clear()
    lines.clear()

    assert factory.components["board"].recipes["standard"]["steel"] == ONE
    assert list(factory.lines) == ["press"]
    assert list(factory.lines["press"].items) == ["bolt"]
    assert list(factory.customers["shop"].products) == ["bolt"]
