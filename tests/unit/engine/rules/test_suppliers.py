from decimal import Decimal

from factory_simulator.engine import (
    Buy,
    Cash,
    Delivery,
    Factory,
    Scenario,
    SupplierOrder,
    World,
)
from factory_simulator.engine.rules.suppliers import (
    catalogue_price,
    delivery_outcome,
    lead_time_used,
)

ZERO = Decimal(0)
ONE = Decimal(1)
ENTRY = "suppliers.mill.catalogue.steel"


def supplier_world(
    parameters: dict[str, Decimal] | None = None,
    deliveries: dict[str, tuple[Delivery, ...]] | None = None,
    express_deliveries: dict[str, tuple[Delivery, ...]] | None = None,
    prices: dict[str, tuple[Decimal, ...]] | None = None,
) -> World:
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
    return World(
        factory=factory,
        scenario=Scenario(horizon=3),
        parameters=parameters or {},
        drawn=frozenset(),
        demand={},
        deliveries=deliveries or {},
        yields={},
        breakdowns={},
        express_deliveries=express_deliveries or {},
        prices=prices or {},
    )


def engine_buy(express: bool) -> Buy:
    return Buy(
        kind="buy",
        supplier="mill",
        material="steel",
        quantity=Decimal(5),
        express=express,
    )


def engine_delivery(period: int, delay: int) -> Delivery:
    return Delivery(
        period=period,
        punctual=delay == 0,
        delay=delay,
        completeness=ONE,
        acceptance=ONE,
    )


def test_an_express_order_takes_the_express_lead_time_and_a_normal_one_its_lead_time():
    lead_times = {f"{ENTRY}.lead_time": Decimal(4), f"{ENTRY}.express_lead_time": ONE}
    world = supplier_world(parameters=lead_times)
    placed = SupplierOrder(
        id="buy-1-1",
        supplier="mill",
        material="steel",
        warehouse="main",
        quantity=Decimal(5),
        open_quantity=Decimal(5),
        unit_price=ONE,
        express=True,
        placed=1,
        arrival=2,
    )

    assert lead_time_used(engine_buy(express=False), world) == 4
    assert lead_time_used(engine_buy(express=True), world) == 1
    assert lead_time_used(placed, world) == 1


def test_an_order_takes_the_delivery_outcome_of_its_kind_and_placing_period():
    world = supplier_world(
        deliveries={
            "mill/steel": (
                engine_delivery(1, 0),
                engine_delivery(2, 1),
                engine_delivery(3, 2),
            )
        },
        express_deliveries={
            "mill/steel": (engine_delivery(1, 3), engine_delivery(2, 4))
        },
    )

    assert delivery_outcome(engine_buy(express=False), 2, world).delay == 1
    assert delivery_outcome(engine_buy(express=False), 3, world).delay == 2
    assert delivery_outcome(engine_buy(express=True), 2, world).delay == 4


def test_a_price_drawn_every_period_gives_the_price_of_the_period():
    every_period = supplier_world(
        parameters={f"{ENTRY}.price": Decimal(9)},
        prices={"mill/steel": (Decimal("2.30"), Decimal("2.56"), Decimal("2.41"))},
    )
    once = supplier_world(parameters={f"{ENTRY}.price": Decimal(9)})

    assert catalogue_price("mill", "steel", 3, every_period) == Decimal("2.41")
    assert catalogue_price("mill", "steel", 3, once) == 9
