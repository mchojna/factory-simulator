from decimal import Decimal

from factory_simulator.engine import (
    Cash,
    Customer,
    CustomerProduct,
    Factory,
    LedgerRow,
    Outcome,
    Product,
    Repair,
    Scenario,
    State,
    World,
)
from factory_simulator.engine.measures.closed import (
    ClosedPeriod,
    costs_by_reference,
    customer_keys,
    ratio,
)

ZERO = Decimal(0)
ONE = Decimal(1)


def keys_world() -> World:
    terms = CustomerProduct(
        price=Decimal(5),
        transport_cost=ZERO,
        demand=Decimal(10),
        lead_time=1,
        patience=1,
        late_penalty=ZERO,
        lost_sale_penalty=ZERO,
    )
    product = Product(
        space=ONE, storage_cost=ZERO, salvage_value=ZERO, recipes={"r": {}}
    )
    factory = Factory(
        materials={},
        components={},
        products={"nut": product, "bolt": product, "washer": product},
        suppliers={},
        customers={
            "shop": Customer(products={"nut": terms, "bolt": terms}),
            "depot": Customer(products={"nut": terms}),
        },
        lines={},
        warehouses={},
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
    )
    return World(
        factory=factory,
        scenario=Scenario(horizon=1),
        parameters={},
        drawn=frozenset(),
        demand={},
        deliveries={},
        yields={},
        breakdowns={},
    )


def row(kind: str, amount: str, reference: str) -> LedgerRow:
    return LedgerRow(
        period=1,
        step="close_period",
        kind=kind,
        amount=Decimal(amount),
        cash_after=ZERO,
        reference=reference,
    )


def test_a_ratio_is_rounded_half_to_even_to_12_places_and_none_over_0():
    assert ratio(Decimal(2), Decimal(3)) == Decimal("0.666666666667")
    assert ratio(Decimal("0.0000000000005"), ONE) == Decimal("0.000000000000")
    assert ratio(Decimal("0.0000000000015"), ONE) == Decimal("0.000000000002")
    assert ratio(Decimal(4), ZERO) is None


def test_the_keys_of_a_customer_measure_are_the_total_customers_products_and_pairs():
    # Every product has a key, the washer no customer buys too; each part is sorted.
    assert customer_keys(keys_world()) == [
        "total",
        "customers.depot",
        "customers.shop",
        "products.bolt",
        "products.nut",
        "products.washer",
        "pairs.depot/nut",
        "pairs.shop/bolt",
        "pairs.shop/nut",
    ]


def test_the_costs_of_a_kind_are_the_positive_amounts_of_its_rows_by_reference():
    ledger = (
        row("storage_cost", "-2.50", "main/steel"),
        row("storage_cost", "-1.25", "main/bolt"),
        row("repair_cost", "-9.00", "repair-1-1"),
    )
    state = State(
        period=1, cash=ZERO, stock={}, condition={}, customer_orders=(), ledger=ledger
    )

    assert costs_by_reference("storage_cost", state) == {
        "main/steel": Decimal("2.50"),
        "main/bolt": Decimal("1.25"),
    }


def test_a_closed_period_gives_its_events_of_a_kind_and_its_accepted_decisions():
    repair = Repair(kind="repair", line="press", amount=Decimal("0.5"))
    outcomes = (
        Outcome(decision_id="1-1", decision=repair, accepted=True, reference="r-1"),
        Outcome(decision_id="1-2", decision=repair, accepted=False, reason="x"),
    )
    period_events = (
        {"kind": "breakdown", "reference": "press"},
        {"kind": "repair", "reference": "press"},
        {"kind": "breakdown", "reference": "saw"},
    )
    state = State(
        period=1,
        cash=ZERO,
        stock={},
        condition={},
        customer_orders=(),
        outcomes=outcomes,
        period_events=period_events,
    )
    period = ClosedPeriod(
        state=state,
        world=keys_world(),
        customer_orders={},
        supplier_orders={},
        production={},
    )

    assert [event["reference"] for event in period.events("breakdown")] == [
        "press",
        "saw",
    ]
    assert period.accepted(Repair) == [("r-1", repair)]
