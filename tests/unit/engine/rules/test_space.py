from decimal import Decimal

from factory_simulator.engine import (
    Cash,
    Factory,
    Line,
    LineItem,
    MadeItem,
    Material,
    Product,
    Production,
    Scenario,
    SupplierOrder,
    TransferOnTheWay,
    Warehouse,
    World,
)
from factory_simulator.engine.rules.space import reserved_space, stock_space

ZERO = Decimal(0)
ONE = Decimal(1)


# A factory of steel (space 2), boards (space 3) and bolts (space 5), with a press at
# `east` and a second warehouse `west`.
def space_world() -> World:
    press = Line(
        capacity=Decimal(40),
        wear_per_period=ZERO,
        wear_per_hour=ZERO,
        breakdown_chance=ZERO,
        breakdown_loss=ZERO,
        repair_cost=ZERO,
        repair_time=ZERO,
        repair_limit=ONE,
        items={"bolt": LineItem(time=ONE, cost=ONE, yield_=ONE)},
        warehouse="east",
    )
    factory = Factory(
        materials={
            "steel": Material(space=Decimal(2), storage_cost=ZERO, salvage_value=ZERO)
        },
        components={
            "board": MadeItem(
                space=Decimal(3),
                storage_cost=ZERO,
                salvage_value=ZERO,
                recipes={"r": {"steel": ONE}},
            )
        },
        products={
            "bolt": Product(
                space=Decimal(5),
                storage_cost=ZERO,
                salvage_value=ZERO,
                recipes={"r": {"board": ONE}},
            )
        },
        suppliers={},
        customers={},
        lines={"press": press},
        warehouses={
            "east": Warehouse(capacity=Decimal(1000)),
            "west": Warehouse(capacity=Decimal(1000)),
        },
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
    )
    return World(
        factory=factory,
        scenario=Scenario(horizon=4),
        parameters={},
        drawn=frozenset(),
        demand={},
        deliveries={},
        yields={},
        breakdowns={},
    )


def supplier_order(warehouse: str, open_quantity: str) -> SupplierOrder:
    return SupplierOrder(
        id=f"buy-1-{warehouse}",
        supplier="mill",
        material="steel",
        warehouse=warehouse,
        quantity=Decimal(10),
        open_quantity=Decimal(open_quantity),
        unit_price=ONE,
        express=False,
        placed=1,
        arrival=3,
    )


def test_the_stock_of_a_warehouse_takes_the_space_of_each_unit_of_each_item():
    stock = {"steel": Decimal("1.5"), "board": Decimal(2), "bolt": ZERO}

    # 1.5 * 2 + 2 * 3 + 0 * 5 = 9.
    assert stock_space(stock, space_world()) == Decimal("9.0")


def test_a_warehouse_reserves_its_production_its_open_orders_and_its_transfers_in():
    production = [
        Production(
            id="make-1-1",
            line="press",
            item="bolt",
            recipe="r",
            started=Decimal(2),
            start=1,
            ready=2,
            overtime=False,
        )
    ]
    orders = [supplier_order("east", "4"), supplier_order("west", "7")]
    transfers = [
        TransferOnTheWay(
            id="transfer-1-1",
            item="board",
            quantity=Decimal(3),
            source="west",
            destination="east",
            arrival=2,
        ),
        TransferOnTheWay(
            id="transfer-1-2",
            item="board",
            quantity=Decimal(1),
            source="east",
            destination="west",
            arrival=2,
        ),
    ]
    world = space_world()

    # East: 2 bolts made by its press, 2 * 5 = 10; 4 open units of steel, 4 * 2 = 8;
    # 3 boards on the way in, 3 * 3 = 9. West: 7 * 2 = 14 and 1 * 3 = 3.
    assert reserved_space("east", production, orders, transfers, world) == 27
    assert reserved_space("west", production, orders, transfers, world) == 17
