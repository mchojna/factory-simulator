from dataclasses import replace
from decimal import Decimal
from typing import Any

from factory_simulator.benchmark.models.inputs import (
    Arrival,
    BuyOption,
    Cash,
    Customer,
    CustomerOrder,
    CustomerProduct,
    Hours,
    Item,
    Line,
    LineItem,
    PlanningInput,
    Warehouse,
    WindowStart,
)


# The plain tiny factory of `tests/factories/bodies.py` from its start: 3 periods,
# cash 1000, 16 chips and 8 boards, an order of 4 monitors due and lost in each period.
def plain_tiny_planning(horizon: int = 3) -> PlanningInput:
    periods = range(1, horizon + 1)
    ones = {period: Decimal(1) for period in periods}
    zero = Decimal(0)
    items = {
        "chip": Item(
            space=Decimal("0.01"),
            storage_cost=zero,
            salvage_value=Decimal("0.1"),
            recipes={},
        ),
        "board": Item(
            space=Decimal("0.02"),
            storage_cost=zero,
            salvage_value=Decimal("0.5"),
            recipes={"standard": {"chip": Decimal(2)}},
        ),
        "monitor": Item(
            space=Decimal("0.15"),
            storage_cost=zero,
            salvage_value=Decimal(2),
            recipes={"standard": {"board": Decimal(2)}},
        ),
    }
    line = Line(
        warehouse="main",
        capacity=Decimal(10),
        wear_per_period=zero,
        wear_per_hour=zero,
        repair_cost=zero,
        repair_time=Decimal(1),
        repair_limit=Decimal(1),
        overtime_hours=zero,
        overtime_cost=zero,
        items={
            "board": LineItem(
                time=Decimal("0.1"), cost=Decimal(1), lead_time=1, good_shares=ones
            ),
            "monitor": LineItem(
                time=Decimal("0.5"), cost=Decimal(2), lead_time=1, good_shares=ones
            ),
        },
        hour_shares=ones,
        kept_conditions=ones,
    )
    warehouse = Warehouse(
        capacity=Decimal(100),
        storage_factor=Decimal(1),
        transport_factor=Decimal(1),
        accepts=tuple(sorted(items)),
    )
    monitor_terms = CustomerProduct(
        price=Decimal(50),
        transport_cost=Decimal(1),
        late_penalty=Decimal(2),
        lost_sale_penalty=Decimal(10),
    )
    state = WindowStart(
        cash=Decimal(1000),
        stock={"main": {"chip": Decimal(16), "board": Decimal(8), "monitor": zero}},
        conditions={"line-1": Decimal(1)},
        hours={"line-1": Hours(regular=Decimal(10), repair=Decimal(10), overtime=zero)},
        production=(),
        transfers=(),
        supplier_orders=(),
        receivables=(),
    )
    orders = tuple(
        CustomerOrder(
            id=f"order-{period}-1",
            customer="distributor",
            product="monitor",
            open_quantity=Decimal(4),
            arrival=period,
            due=period,
            last=period,
        )
        for period in periods
    )
    buy_options = tuple(
        BuyOption(
            supplier="chip-maker",
            material="chip",
            period=period,
            express=False,
            unit_price=Decimal("0.5"),
            limit=Decimal(1000),
            arrivals=(
                (Arrival(period=period + 1, accepted=Decimal(1), left_open=zero),)
                if period < horizon
                else ()
            ),
        )
        for period in periods
    )
    return PlanningInput(
        first_period=1,
        window_end=horizon,
        horizon=horizon,
        starting_cash=Decimal(1000),
        items=items,
        lines={"line-1": line},
        warehouses={"main": warehouse},
        routes=(),
        customers={
            "distributor": Customer(
                payment_terms=0, products={"monitor": monitor_terms}
            )
        },
        cash=Cash(
            credit_limit=zero,
            credit_interest=zero,
            debit_interest=zero,
            overdraft_interest=zero,
        ),
        state=state,
        customer_orders=orders,
        buy_options=buy_options,
    )


# The world of a large selling price as the reference reads it: the plain tiny factory
# for one period from cash 1000, 0.001 chip and 1 monitor, an order of 1 monitor due
# now at a price, a line of 0.001 hours, a warehouse of capacity 1 and chips up to a
# buy limit, 0.001 by default. A ship earns the price less 1 of transport plus 0.0001
# of chip salvage: 999999999999999999.0001 at a price of 10**18.
def solver_scale_planning(
    price: Decimal, buy_limit: Decimal = Decimal("0.001")
) -> PlanningInput:
    planning = plain_tiny_planning(horizon=1)
    tiny = Decimal("0.001")
    line = replace(planning.lines["line-1"], capacity=tiny)
    warehouse = replace(planning.warehouses["main"], capacity=Decimal(1))
    customer = planning.customers["distributor"]
    terms = replace(customer.products["monitor"], price=price)
    zero = Decimal(0)
    state = replace(
        planning.state,
        stock={"main": {"chip": tiny, "board": zero, "monitor": Decimal(1)}},
        hours={"line-1": Hours(regular=tiny, repair=tiny, overtime=zero)},
    )
    order = replace(
        planning.customer_orders[0],
        id="order-0-1",
        open_quantity=Decimal(1),
        arrival=0,
    )
    option = replace(planning.buy_options[0], limit=buy_limit)
    return replace(
        planning,
        lines={"line-1": line},
        warehouses={"main": warehouse},
        customers={"distributor": replace(customer, products={"monitor": terms})},
        state=state,
        customer_orders=(order,),
        buy_options=(option,),
    )


# The description of a run of the plain tiny factory of `tests/factories/bodies.py`,
# as `POST /runs` gives it.
def plain_tiny_description() -> dict[str, Any]:
    zero, one = 0, 1
    item = {"storage_cost": zero, "description": None, "name": None, "unit": None}
    line_item = {"changeover_cost": None, "changeover_time": None, "lead_time": one}
    return {
        "linear": True,
        "manifest": {
            "cash": {
                "credit_interest": zero,
                "credit_limit": zero,
                "debit_interest": zero,
                "overdraft_interest": zero,
            },
            "materials": {
                "chip": item
                | {"salvage_value": Decimal("0.1"), "space": Decimal("0.01")}
            },
            "components": {
                "board": item
                | {
                    "default_recipe": "standard",
                    "recipes": {"standard": {"chip": 2}},
                    "salvage_value": Decimal("0.5"),
                    "space": Decimal("0.02"),
                }
            },
            "products": {
                "monitor": item
                | {
                    "default_recipe": "standard",
                    "recipes": {"standard": {"board": 2}},
                    "salvage_value": 2,
                    "space": Decimal("0.15"),
                }
            },
            "customers": {
                "distributor": {
                    "payment_terms": zero,
                    "products": {
                        "monitor": {
                            "demand": 4,
                            "demand_persistence": None,
                            "late_penalty": 2,
                            "lead_time": zero,
                            "lost_sale_penalty": 10,
                            "patience": zero,
                            "price": 50,
                            "transport_cost": one,
                        }
                    },
                }
            },
            "groups": {},
            "lines": {
                "line-1": {
                    "breakdown_chance": zero,
                    "breakdown_loss": zero,
                    "capacity": 10,
                    "items": {
                        "board": line_item
                        | {"cost": one, "time": Decimal("0.1"), "yield": one},
                        "monitor": line_item
                        | {"cost": 2, "time": Decimal("0.5"), "yield": one},
                    },
                    "overtime_cost": None,
                    "overtime_hours": zero,
                    "repair_cost": zero,
                    "repair_limit": one,
                    "repair_time": one,
                    "warehouse": None,
                    "wear_per_hour": zero,
                    "wear_per_period": zero,
                }
            },
            "routes": {},
            "suppliers": {
                "chip-maker": {
                    "catalogue": {
                        "chip": {
                            "acceptance": one,
                            "backfill_delay": zero,
                            "cancellation_fee": zero,
                            "completeness": one,
                            "delay": one,
                            "discounts": [],
                            "express_cost": None,
                            "express_lead_time": None,
                            "lead_time": one,
                            "max_quantity": 1000,
                            "min_quantity": None,
                            "price": Decimal("0.5"),
                            "punctuality": one,
                        }
                    }
                }
            },
            "warehouses": {
                "main": {
                    "accepts": ["materials", "components", "products"],
                    "capacity": 100,
                    "storage_factor": one,
                    "transport_factor": one,
                }
            },
        },
        "scenario": {
            "demand_shapes": [],
            "forecasts": [],
            "hidden": [],
            "horizon": 3,
            "random_disruptions": [],
            "start": {"cash": 1000},
        },
    }


# The observation of period 1 of the plain tiny run.
def plain_tiny_observation() -> dict[str, Any]:
    return {
        "period": 1,
        "horizon": 3,
        "cash": 1000,
        "customer_orders": [
            {
                "arrival": 1,
                "customer": "distributor",
                "due": 1,
                "id": "order-1-1",
                "last": 1,
                "product": "monitor",
                "quantity": 4,
                "shipped": 0,
            }
        ],
        "disruptions": [],
        "forecasts": {},
        "prices": {},
        "lines": {
            "line-1": {
                "condition": 1,
                "overtime_hours_available": 0,
                "regular_hours_available": 10,
                "repair_hours_available": 10,
            }
        },
        "production": [],
        "receivables": [],
        "stock": {"main": {"board": 8, "chip": 16, "monitor": 0}},
        "supplier_orders": [],
        "transfers": [],
    }


# The description of the plain tiny run with the yield of boards hidden, and the
# description of its twin, which shows that yield as a range with its cut mean.
def hidden_and_shown_yield() -> tuple[dict[str, Any], dict[str, Any]]:
    hidden = plain_tiny_description()
    del hidden["manifest"]["lines"]["line-1"]["items"]["board"]["yield"]
    hidden["scenario"]["hidden"] = ["lines.items.yield"]
    shown = plain_tiny_description()
    shown["manifest"]["lines"]["line-1"]["items"]["board"]["yield"] = {
        "min": Decimal("0.8000"),
        "max": Decimal("1.0000"),
        "cut_mean": Decimal("0.900000"),
    }
    return hidden, shown
