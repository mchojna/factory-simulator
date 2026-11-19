from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal

import pytest
from factories import draw_world_of_bodies, tiny_manifest, tiny_scenario
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.engine import (
    Cash,
    Receivable,
    build_state,
    compute_interest,
    compute_profit,
)

CASH_TERMS = Cash(
    credit_limit=Decimal("1000"),
    credit_interest=Decimal("0.0005"),
    debit_interest=Decimal("0.0040"),
    overdraft_interest=Decimal("0.0200"),
)


money = st.decimals(min_value=-(10**9), max_value=10**9, places=4)


rates = st.lists(
    st.decimals(min_value=0, max_value=1, places=4), min_size=3, max_size=3
).map(sorted)


def test_profit_is_cash_less_the_start_plus_receivables_plus_salvage():
    # 900 - 1000 + 30 + 10 * 2 = -50.
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    receivable = Receivable(
        shipment="ship-4-1",
        customer="distributor",
        amount=Decimal("30.0000"),
        payment_period=6,
    )
    state = replace(
        build_state(world),
        cash=Decimal("900.0000"),
        stock={"main": {"monitor": Decimal("10.000")}},
        receivables=(receivable,),
    )

    assert compute_profit(state, world) == Decimal("-50.0000")


@pytest.mark.parametrize(
    ("cash", "interest"),
    [
        ("-1500", "-14.0000"),
        ("-400", "-1.6000"),
        ("2000", "1.0000"),
        ("1167.18", "0.5835"),
        ("0", "0.0000"),
    ],
)
def test_interest_follows_the_worked_examples(cash: str, interest: str):
    result = compute_interest(Decimal(cash), CASH_TERMS)
    assert result.as_tuple() == Decimal(interest).as_tuple()


def test_interest_paid_is_rounded_up_against_the_factory():
    terms = replace(CASH_TERMS, debit_interest=Decimal("0.0005"))

    assert compute_interest(Decimal("-0.01"), terms) == Decimal("-0.0001")


@pytest.mark.property
@given(money, money.map(abs), rates)
def test_interest_charges_each_part_of_cash_at_its_rate(
    cash: Decimal, limit: Decimal, drawn_rates: list[Decimal]
):
    credit, debit, overdraft = drawn_rates
    terms = Cash(
        credit_limit=limit,
        credit_interest=credit,
        debit_interest=debit,
        overdraft_interest=overdraft,
    )
    positive = max(cash, Decimal(0))
    down_to_limit = min(max(-cash, Decimal(0)), limit)
    below_limit = max(-cash - limit, Decimal(0))
    expected = positive * credit - down_to_limit * debit - below_limit * overdraft
    assert compute_interest(cash, terms) == expected.quantize(
        Decimal("0.0001"), rounding=ROUND_FLOOR
    )
