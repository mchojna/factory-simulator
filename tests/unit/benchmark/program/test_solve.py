import math
import os
import pickle
import random
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from factories import example_count, plain_tiny_planning, solver_scale_planning
from hypothesis import example, given, settings
from hypothesis import strategies as st
from scipy.optimize import Bounds, OptimizeResult

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
    Receivable,
    Route,
    SupplierOrder,
    TerminalValue,
    Tier,
    TransferOnTheWay,
    Warehouse,
    WindowStart,
)
from factory_simulator.benchmark.models.outputs import IntegerSolve, LinearSolve
from factory_simulator.benchmark.program import solve as solve_module
from factory_simulator.benchmark.program.decisions import decisions_json
from factory_simulator.benchmark.program.solve import (
    GAP_LIMIT,
    Expression,
    Program,
    UnsupportedScaleError,
    build_money_unit,
    build_program,
    changeover_lines,
    penalty_periods,
    read_integer_solve,
    solve_integer,
    solve_program,
    solve_relaxed,
)

BUILD_AND_SOLVE = """
import pickle
import sys

from factory_simulator.benchmark.program.decisions import decisions_json
from factory_simulator.benchmark.program.solve import build_program, solve_program

planning = pickle.loads(sys.stdin.buffer.read())
program = build_program(planning, with_rounding=False)
print(list(program.variables))
print(program.at_most_rows)
print(program.equal_rows)
print(decisions_json(solve_program(planning), planning))
"""

ZERO = Decimal(0)
MONITOR = {"standard": {"chip": Decimal(1)}}
LIMITS = {"node_limit": 1000, "mip_rel_gap": 0.0, "mip_abs_gap": 0.01}
SOLUTION_LIMIT = (
    "The HiGHS status code was not recognized. (HiGHS Status 16: model_status is "
    "Solution limit reached; primal_status is None)"
)
UNKNOWN = (
    "The HiGHS status code was not recognized. (HiGHS Status 15: model_status is "
    "Unknown; primal_status is Feasible)"
)
UNBOUNDED_OR_INFEASIBLE = (
    "The problem is unbounded or infeasible. (HiGHS Status 9: model_status is Primal "
    "infeasible or unbounded; primal_status is None)"
)

# The seconds a call of HiGHS may run past its time limit, and the work around it.
CALL_OVERHEAD = 1.0

# Amounts of money from -10**9 to 10**9.
money_values = st.floats(min_value=-(10**9), max_value=10**9, allow_nan=False)


def order(order_id: str, product: str, quantity: int, due: int) -> CustomerOrder:
    return CustomerOrder(
        id=order_id,
        customer="distributor",
        product=product,
        open_quantity=Decimal(quantity),
        arrival=1,
        due=due,
        last=due,
    )


# One chip and monitors made of 1.000 chip on one line with cost 2.0000 and lead time
# 1, sold at 20.0000, without storage, interest, transport or penalties.
def chip_planning(
    horizon: int,
    orders: tuple[CustomerOrder, ...],
    chip_salvage: Decimal = Decimal(1),
    min_quantity: Decimal = ZERO,
    tiers: tuple[Tier, ...] = (),
    monitors: tuple[str, ...] = ("monitor",),
    changeover_cost: Decimal = ZERO,
    chips_in_stock: Decimal = ZERO,
) -> PlanningInput:
    periods = range(1, horizon + 1)
    ones = {period: Decimal(1) for period in periods}
    items = {
        "chip": Item(
            space=Decimal("0.001"),
            storage_cost=ZERO,
            salvage_value=chip_salvage,
            recipes={},
        )
    } | {
        monitor: Item(
            space=Decimal("0.001"),
            storage_cost=ZERO,
            salvage_value=ZERO,
            recipes=MONITOR,
        )
        for monitor in monitors
    }
    line = Line(
        warehouse="main",
        capacity=Decimal(1000),
        wear_per_period=ZERO,
        wear_per_hour=ZERO,
        repair_cost=ZERO,
        repair_time=Decimal(1),
        repair_limit=Decimal(1),
        overtime_hours=ZERO,
        overtime_cost=ZERO,
        items={
            monitor: LineItem(
                time=Decimal("0.01"),
                cost=Decimal(2),
                lead_time=1,
                good_shares=ones,
                changeover_cost=changeover_cost,
            )
            for monitor in monitors
        },
        hour_shares=ones,
        kept_conditions=ones,
    )
    state = WindowStart(
        cash=Decimal(10000),
        stock={"main": {"chip": chips_in_stock} | dict.fromkeys(monitors, ZERO)},
        conditions={"line-1": Decimal(1)},
        hours={
            "line-1": Hours(regular=Decimal(1000), repair=Decimal(1000), overtime=ZERO)
        },
        production=(),
        transfers=(),
        supplier_orders=(),
        receivables=(),
        set_for={"line-1": None},
    )
    terms = CustomerProduct(
        price=Decimal(20),
        transport_cost=ZERO,
        late_penalty=ZERO,
        lost_sale_penalty=ZERO,
    )
    buy_options = tuple(
        BuyOption(
            supplier="chip-maker",
            material="chip",
            period=period,
            express=False,
            unit_price=Decimal(5),
            limit=Decimal(1000),
            arrivals=(
                (Arrival(period=period + 1, accepted=Decimal(1), left_open=ZERO),)
                if period < horizon
                else ()
            ),
            min_quantity=min_quantity,
            tiers=tiers,
        )
        for period in periods
    )
    return PlanningInput(
        first_period=1,
        window_end=horizon,
        horizon=horizon,
        starting_cash=Decimal(10000),
        items=items,
        lines={"line-1": line},
        warehouses={
            "main": Warehouse(
                capacity=Decimal(1000),
                storage_factor=Decimal(1),
                transport_factor=Decimal(1),
                accepts=tuple(sorted(items)),
            )
        },
        routes=(),
        customers={
            "distributor": Customer(
                payment_terms=0, products=dict.fromkeys(monitors, terms)
            )
        },
        cash=Cash(
            credit_limit=ZERO,
            credit_interest=ZERO,
            debit_interest=ZERO,
            overdraft_interest=ZERO,
        ),
        state=state,
        customer_orders=orders,
        buy_options=buy_options,
    )


def result_of(**fields: object) -> OptimizeResult:
    result = OptimizeResult()
    result.update(fields)
    return result


# Window 2 from period 1, the chips of period 2 arriving after it, every unit at the
# end up to its expected use worth `factor` times its cost of 0.5, 2 or 6.
def window_of_two(factor: Decimal) -> PlanningInput:
    planning = plain_tiny_planning(horizon=2)
    buy_options = tuple(
        replace(
            option,
            arrivals=(
                Arrival(
                    period=option.period + 1, accepted=Decimal(1), left_open=Decimal(0)
                ),
            ),
        )
        for option in planning.buy_options
    )
    terminal_values = {
        "chip": TerminalValue(value=factor * Decimal("0.5"), expected_use=Decimal(48)),
        "board": TerminalValue(value=factor * 2, expected_use=Decimal(24)),
        "monitor": TerminalValue(value=factor * 6, expected_use=Decimal(12)),
    }
    return replace(planning, buy_options=buy_options, terminal_values=terminal_values)


@pytest.mark.slow
def test_2_processes_build_the_same_program():
    planning = pickle.dumps(plain_tiny_planning())
    source = str(Path(__file__).parents[4] / "src")
    python_path = os.pathsep.join(
        part for part in (source, os.environ.get("PYTHONPATH", "")) if part
    )

    outputs = [
        subprocess.run(
            [sys.executable, "-c", BUILD_AND_SOLVE],
            input=planning,
            capture_output=True,
            check=True,
            env=os.environ | {"PYTHONHASHSEED": hash_seed, "PYTHONPATH": python_path},
        ).stdout
        for hash_seed in ("1", "2")
    ]

    assert outputs[0] == outputs[1]


def test_the_plain_tiny_factory_makes_monitors_from_its_boards_and_chips():
    solution = solve_program(plain_tiny_planning())

    assert solution.value == pytest.approx(328)
    assert solution.ships == ()
    assert solution.buys == ()
    made = sorted(solution.produces, key=lambda produce: produce.item)
    assert [(produce.item, produce.recipe, produce.overtime) for produce in made] == [
        ("board", "standard", False),
        ("monitor", "standard", False),
    ]
    assert [produce.quantity for produce in made] == pytest.approx([8, 4])


def test_purchase_budget_constrains_the_current_period_buy_cost():
    planning = replace(
        chip_planning(3, (order("order-1-1", "monitor", 4, 3),)),
        purchase_budget_cap=Decimal(10),
    )

    solution = solve_program(planning)
    buys = [
        decision
        for decision in decisions_json(solution, planning)
        if decision["kind"] == "buy"
    ]
    value = Decimal(0)
    for decision in buys:
        option = next(
            option
            for option in planning.buy_options
            if option.period == planning.first_period
            and option.supplier == decision["supplier"]
            and option.material == decision["material"]
            and option.express == decision["express"]
        )
        value += decision["quantity"] * option.unit_price

    assert value <= Decimal(10)


def test_purchase_budget_also_constrains_the_relaxed_program():
    planning = chip_planning(3, (order("order-1-1", "monitor", 4, 3),))

    unrestricted = solve_relaxed(planning)
    constrained = solve_relaxed(replace(planning, purchase_budget_cap=Decimal(10)))

    assert constrained < unrestricted


def test_disabled_purchase_budget_preserves_native_optimizer_decisions():
    planning = chip_planning(3, (order("order-1-1", "monitor", 4, 3),))
    explicitly_disabled = replace(planning, purchase_budget_cap=None)

    native = decisions_json(solve_program(planning), planning)
    disabled = decisions_json(solve_program(explicitly_disabled), explicitly_disabled)

    assert disabled == native


# Every rate is 0, so a start cash of -1000 shifts the cash at the close and the
# objective by the same amount as a start cash of 1000.
def test_a_start_below_the_credit_limit_plays_as_a_start_above_it():
    planning = plain_tiny_planning()
    cash = Decimal(-1000)
    planning = replace(
        planning, starting_cash=cash, state=replace(planning.state, cash=cash)
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(328)
    produced = [
        (decision["item"], decision["quantity"])
        for decision in decisions_json(solution, planning)
        if decision["kind"] == "produce"
    ]
    assert sorted(produced) == [
        ("board", Decimal("8.000")),
        ("monitor", Decimal("4.000")),
    ]


def test_one_period_ships_the_order_and_keeps_the_rest_at_salvage_value():
    planning = plain_tiny_planning(horizon=1)
    stock = {"main": {"chip": Decimal(0), "board": Decimal(0), "monitor": Decimal(10)}}
    planning = replace(planning, state=replace(planning.state, stock=stock))

    solution = solve_program(planning)

    assert [(ship.order, ship.warehouse) for ship in solution.ships] == [
        ("order-1-1", "main")
    ]
    assert solution.ships[0].quantity == pytest.approx(4)
    assert solution.value == pytest.approx(4 * (50 - 1) + 6 * 2)


def test_positive_cash_earns_the_credit_rate_at_the_close():
    planning = plain_tiny_planning(horizon=1)
    stock = {"main": {"chip": Decimal(0), "board": Decimal(0), "monitor": Decimal(0)}}
    rate = Decimal("0.01")
    rates = replace(
        planning.cash,
        credit_interest=rate,
        debit_interest=rate,
        overdraft_interest=rate,
    )
    planning = replace(
        planning,
        state=replace(planning.state, stock=stock),
        cash=rates,
        customer_orders=(),
    )

    assert solve_program(planning).value == pytest.approx(10)


# Three periods with 40 boards and no hours in period 1: the monitors made in period 2
# ship in period 3 to an order of 20.
# 5 hours make 10 monitors from 20 boards: revenue 500, transport 10, production
# 20, 10 units lost at 10 and 20 boards left at 0.5.
def test_a_breakdown_loss_of_0_5_halves_the_hours_of_its_period():
    planning = plain_tiny_planning()
    line = replace(
        planning.lines["line-1"],
        kept_conditions={1: Decimal(1), 2: Decimal("0.5"), 3: Decimal(1)},
    )
    zero = Decimal(0)
    stock = {"main": {"chip": zero, "board": Decimal(40), "monitor": zero}}
    hours = {"line-1": Hours(regular=zero, repair=zero, overtime=zero)}
    order = CustomerOrder(
        id="order-3-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(20),
        arrival=3,
        due=3,
        last=3,
    )
    planning = replace(
        planning,
        lines={"line-1": line},
        state=replace(planning.state, stock=stock, hours=hours),
        customer_orders=(order,),
        buy_options=(),
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(500 - 10 - 20 - 100 + 10)


# 3 items in 1 warehouse over 3 periods give 9 stock rows, the condition of line-1
# into periods 2 and 3 gives 2 rows and the cash of the 3 periods 3 rows.
def test_the_program_of_the_plain_tiny_factory_has_14_equality_rows():
    program = build_program(plain_tiny_planning(), with_rounding=False)

    assert len(program.equal_rows) == 14


def test_a_line_with_a_changeover_cost_is_a_changeover_line():
    planning = plain_tiny_planning()
    line = planning.lines["line-1"]
    board = replace(line.items["board"], changeover_cost=Decimal(50))
    lines = {"line-1": replace(line, items={**line.items, "board": board})}

    assert changeover_lines(planning) == []
    assert changeover_lines(replace(planning, lines=lines)) == ["line-1"]


def test_the_relaxed_value_of_the_plain_tiny_factory_is_its_value_as_nothing_rounds():
    assert solve_relaxed(plain_tiny_planning()) == pytest.approx(328)


def test_a_relaxed_solve_holds_its_declared_time_limit():
    diagnostics: list[LinearSolve] = []

    assert solve_relaxed(
        plain_tiny_planning(), diagnostics=diagnostics, time_limit=0.25
    ) == pytest.approx(328)
    assert diagnostics[0].time_limit_seconds == 0.25


# Half of the monitors started from the 8 boards come out good; the engine may round
# the good units up by 0.0005, which ships to the order of period 2.
def test_the_relaxed_value_counts_good_units_the_engine_may_round_up():
    planning = plain_tiny_planning(horizon=2)
    line = planning.lines["line-1"]
    shares = {1: Decimal("0.5"), 2: Decimal(1)}
    monitor = replace(line.items["monitor"], good_shares=shares)
    items = {**line.items, "monitor": monitor}
    planning = replace(planning, lines={"line-1": replace(line, items=items)})

    value = solve_program(planning).value

    assert value is not None
    assert solve_relaxed(planning) > value + 0.0005 * 50


# In period 1 the 8 boards make 4 monitors for order-2-1 and the 16 chips 8 boards;
# in period 2 those boards make 4 monitors and 48 chips bought in period 1 make 24
# boards; 48 more chips are at the end, bought in period 1 or in period 2 at the same
# value. The units at the end gain 1 percent of their cost,
# 0.01 * (48 * 0.5 + 24 * 2 + 4 * 6) = 0.96, above the value 156 of the next test.
def test_a_terminal_value_above_cost_buys_chips_for_the_periods_after_the_window():
    solution = solve_program(window_of_two(Decimal("1.01")))

    assert solution.value == pytest.approx(-8 + 196 - 40 + 8 + 0.96)
    assert len(solution.buys) == 1
    assert 48 - 1e-6 <= solution.buys[0].quantity <= 96 + 1e-6


# Every unit at the end is worth what it costs, so no buy gains anything: the 8 boards
# make 4 monitors for order-2-1, order-1-1 is lost and the 16 chips keep their cost.
def test_a_terminal_value_equal_to_cost_gains_nothing_from_a_buy():
    solution = solve_program(window_of_two(Decimal(1)))

    assert solution.value == pytest.approx(-8 + 196 - 40 + 8)


# The window of period 1 alone, the buy of period 1 arriving in period 2.
def window_of_one(terminal_values: dict[str, TerminalValue]) -> PlanningInput:
    planning = plain_tiny_planning()
    return replace(
        planning,
        window_end=1,
        buy_options=planning.buy_options[:1],
        terminal_values=terminal_values,
    )


# Each unit at the end is worth 1.01 times its cost up to the expected use of the
# plain tiny factory: chip 0.505 up to 48, board 2.02 up to 24, monitor 6.06 up to 12.
# A board gains 2.02 - 1 - 2 * 0.5 = 0.02, so the 16 chips make 8 boards; a chip
# bought gains 0.505 - 0.5 = 0.005 up to 48 chips at the end: 16 - 2 * 8 + 48 = 48.
def test_a_one_period_window_with_the_terminal_value_buys_chips():
    solution = solve_program(
        window_of_one(
            {
                "chip": TerminalValue(value=Decimal("0.505"), expected_use=Decimal(48)),
                "board": TerminalValue(value=Decimal("2.02"), expected_use=Decimal(24)),
                "monitor": TerminalValue(
                    value=Decimal("6.06"), expected_use=Decimal(12)
                ),
            }
        )
    )

    assert [buy.quantity for buy in solution.buys] == pytest.approx([48])


# A chip that arrives after the window is worth nothing, and one in stock its salvage
# value 0.1, below its price 0.5.
def test_a_one_period_window_with_salvage_value_buys_nothing():
    solution = solve_program(window_of_one({}))

    assert solution.buys == ()


@pytest.mark.parametrize(
    ("last", "penalties"),
    [
        # The loss in 8 lies after the window.
        (8, [(1, Decimal(2)), (2, Decimal(2)), (3, Decimal(2))]),
        (3, [(1, Decimal(2)), (2, Decimal(2)), (3, Decimal(10))]),
    ],
)
def test_a_lost_sale_counts_in_its_period_only_within_the_window(
    last: int, penalties: list[tuple[int, Decimal]]
):
    planning = replace(plain_tiny_planning(), window_end=3, horizon=8)
    order = CustomerOrder(
        id="order-1-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(4),
        arrival=1,
        due=1,
        last=last,
    )

    assert list(penalty_periods(planning, order)) == penalties


def test_an_order_due_in_the_first_period_of_the_window_pays_from_it():
    planning = replace(plain_tiny_planning(), first_period=2, window_end=3, horizon=8)
    order = CustomerOrder(
        id="order-2-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(4),
        arrival=2,
        due=2,
        last=5,
    )

    assert list(penalty_periods(planning, order)) == [
        (2, Decimal(2)),
        (3, Decimal(2)),
    ]


# 156 as in the previous test, plus 10 chips arriving after the window at their
# terminal value 0.5, as 16 + 10 chips stay below the expected use of 48.
def test_a_transfer_arriving_after_the_window_counts_at_its_terminal_value():
    planning = replace(window_of_two(Decimal(1)), horizon=3)
    transfer = TransferOnTheWay(
        item="chip", quantity=Decimal(10), destination="main", arrival=3
    )
    planning = replace(planning, state=replace(planning.state, transfers=(transfer,)))

    assert solve_program(planning).value == pytest.approx(161)


def test_a_relaxed_program_without_an_optimum_raises_an_error_naming_its_period(
    monkeypatch: pytest.MonkeyPatch,
):
    def unbounded(*_arguments: object, **_keys: object) -> OptimizeResult:
        result = OptimizeResult()
        result.update({"status": 3, "x": None, "message": "unbounded"})
        return result

    monkeypatch.setattr(solve_module, "linprog", unbounded)

    with pytest.raises(RuntimeError, match=r"^period 1: "):
        solve_relaxed(plain_tiny_planning())


# Two periods: the warehouse `centre` holds 8 boards, `main` holds the line and
# nothing else, and order-2-1 of 4 monitors is due and lost in period 2. With lead
# time 0 the 8 boards reach `main` in period 1 at 0.1 each, before production, and
# make 4 monitors that ship in period 2: 4 * 50 - 4 * 1 - 4 * 2 - 8 * 0.1 = 187.2.
# With lead time 1 they arrive in period 2, too late for a monitor to ship, so they
# stay in `centre` at their salvage value and the order is lost: 8 * 0.5 - 4 * 10.
@pytest.mark.parametrize(
    ("lead_time", "sent", "value"), [(0, [8], 187.2), (1, [], -36)]
)
def test_a_transfer_of_lead_time_0_feeds_production_of_its_period(
    lead_time: int, sent: list[int], value: float
):
    planning = plain_tiny_planning(horizon=2)
    centre = replace(planning.warehouses["main"], accepts=("board",))
    route = Route(
        source="centre", destination="main", cost=Decimal("0.1"), lead_time=lead_time
    )
    stock = {
        "main": {"chip": ZERO, "board": ZERO, "monitor": ZERO},
        "centre": {"board": Decimal(8)},
    }
    order = CustomerOrder(
        id="order-2-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(4),
        arrival=2,
        due=2,
        last=2,
    )
    planning = replace(
        planning,
        warehouses={**planning.warehouses, "centre": centre},
        routes=(route,),
        state=replace(planning.state, stock=stock),
        customer_orders=(order,),
        buy_options=(),
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(value)
    assert [transfer.quantity for transfer in solution.transfers] == pytest.approx(sent)


# One period: `centre` holds 4 monitors and order-1-1 of 4 is due and lost in it. A
# ship from `centre` pays transport 1 * 100 for a price of 50, worse than the lost
# sale at 10. Ships run before transfers, so a transfer of lead time 0 to `main`
# cannot reach the ship: the order is lost at 4 * 10 and the monitors stay at 4 * 2.
def test_a_transfer_of_lead_time_0_comes_too_late_for_a_ship_of_its_period():
    planning = plain_tiny_planning(horizon=1)
    centre = replace(
        planning.warehouses["main"],
        transport_factor=Decimal(100),
        accepts=("monitor",),
    )
    route = Route(source="centre", destination="main", cost=Decimal("0.1"), lead_time=0)
    stock = {
        "main": {"chip": ZERO, "board": ZERO, "monitor": ZERO},
        "centre": {"monitor": Decimal(4)},
    }
    planning = replace(
        planning,
        warehouses={**planning.warehouses, "centre": centre},
        routes=(route,),
        state=replace(planning.state, stock=stock),
    )

    solution = solve_program(planning)

    assert solution.ships == ()
    assert solution.value == pytest.approx(-40 + 8)


# Order-1-1 of 4 monitors, due in period 1 and lost in period 3, with nothing to make
# it from: the late penalty of periods 1 and 2 and the lost-sale penalty of period 3,
# 4 * 2 + 4 * 2 + 4 * 10.
def test_an_order_never_shipped_pays_its_late_penalty_before_its_lost_sale():
    planning = plain_tiny_planning()
    stock = {"main": {"chip": ZERO, "board": ZERO, "monitor": ZERO}}
    order = CustomerOrder(
        id="order-1-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(4),
        arrival=1,
        due=1,
        last=3,
    )
    planning = replace(
        planning,
        state=replace(planning.state, stock=stock),
        customer_orders=(order,),
        buy_options=(),
    )

    assert solve_program(planning).value == pytest.approx(-56)


# The same order lost in period 8, after the horizon 3: the end of the run loses it
# in period 3, so it pays the late penalty of periods 1 and 2 and the lost sale of
# period 3. Lost in period 8 it would pay the late penalty of periods 1 to 3 only,
# -24.
def test_an_order_lost_at_the_horizon_before_its_last_period_pays_its_lost_sale():
    planning = plain_tiny_planning()
    stock = {"main": {"chip": ZERO, "board": ZERO, "monitor": ZERO}}
    order = CustomerOrder(
        id="order-1-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(4),
        arrival=1,
        due=1,
        last=8,
    )
    planning = replace(
        planning,
        state=replace(planning.state, stock=stock),
        customer_orders=(order,),
        buy_options=(),
    )

    assert solve_program(planning).value == pytest.approx(-56)


# Revenue paid 2 periods after a shipment of period 1 falls after the window of one
# period and counts as a receivable: 4 * (50 - 1) + 6 * 2, as with payment at once.
def test_revenue_paid_after_the_window_counts_as_a_receivable():
    planning = plain_tiny_planning(horizon=1)
    stock = {"main": {"chip": ZERO, "board": ZERO, "monitor": Decimal(10)}}
    distributor = replace(planning.customers["distributor"], payment_terms=2)
    planning = replace(
        planning,
        state=replace(planning.state, stock=stock),
        customers={"distributor": distributor},
    )

    solution = solve_program(planning)

    assert solution.ships[0].quantity == pytest.approx(4)
    assert solution.value == pytest.approx(4 * (50 - 1) + 6 * 2)


# 2 regular hours make 4 monitors and 2 overtime hours 4 more, from 16 boards, for
# order-2-1 of 8. An overtime unit pays its cost 2 and 0.5 hours at 3: revenue
# 8 * 50, transport 8 * 1, production 8 * 2 and overtime 4 * 0.5 * 3, 400 - 8 - 16 - 6.
def test_production_in_overtime_pays_the_overtime_cost_of_its_hours():
    planning = plain_tiny_planning(horizon=2)
    line = replace(
        planning.lines["line-1"], overtime_hours=Decimal(2), overtime_cost=Decimal(3)
    )
    stock = {"main": {"chip": ZERO, "board": Decimal(16), "monitor": ZERO}}
    hours = {
        "line-1": Hours(regular=Decimal(2), repair=Decimal(2), overtime=Decimal(2))
    }
    order = CustomerOrder(
        id="order-2-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(8),
        arrival=2,
        due=2,
        last=2,
    )
    planning = replace(
        planning,
        lines={"line-1": line},
        state=replace(planning.state, stock=stock, hours=hours),
        customer_orders=(order,),
        buy_options=(),
    )

    solution = solve_program(planning)

    made = sorted((produce.overtime, produce.quantity) for produce in solution.produces)
    assert made == [(False, pytest.approx(4)), (True, pytest.approx(4))]
    assert solution.value == pytest.approx(370)


# Condition 0.5 gives 5 regular hours in period 1, 10 monitors from 20 boards. They
# wear the line by 5 * 0.01, and a repair of 0.5, the most that takes condition to 1,
# costs 0.5 * 20, so period 2 has condition 0.5 - 0.05 + 0.5 = 0.95 and 9.5 hours,
# 19 monitors. Order-3-1 of 30 gets 29: revenue 29 * 50, transport 29, production
# 29 * 2, repair 10, one unit lost at 10 and 2 boards left at 0.5.
def test_a_repair_restores_the_condition_that_wear_takes_from_the_next_period():
    planning = plain_tiny_planning()
    line = replace(
        planning.lines["line-1"], wear_per_hour=Decimal("0.01"), repair_cost=Decimal(20)
    )
    stock = {"main": {"chip": ZERO, "board": Decimal(60), "monitor": ZERO}}
    hours = {"line-1": Hours(regular=Decimal(5), repair=Decimal(10), overtime=ZERO)}
    order = CustomerOrder(
        id="order-3-1",
        customer="distributor",
        product="monitor",
        open_quantity=Decimal(30),
        arrival=3,
        due=3,
        last=3,
    )
    planning = replace(
        planning,
        lines={"line-1": line},
        state=replace(
            planning.state,
            stock=stock,
            conditions={"line-1": Decimal("0.5")},
            hours=hours,
        ),
        customer_orders=(order,),
        buy_options=(),
    )

    solution = solve_program(planning)

    assert [repair.amount for repair in solution.repairs] == pytest.approx([0.5])
    assert solution.value == pytest.approx(1450 - 29 - 58 - 10 - 10 + 1)


# 60 * 20 - 100 * 5 - 60 * 2 + 40 * 1 = 1200 - 500 - 120 + 40.
def test_a_minimum_quantity_buys_100_chips_for_an_order_of_60_monitors():
    planning = chip_planning(
        3, (order("order-1-1", "monitor", 60, 3),), min_quantity=Decimal(100)
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(620)
    assert [(buy.material, buy.quantity) for buy in solution.buys] == [
        ("chip", pytest.approx(100))
    ]


# 60 * 20 - 60 * 5 - 60 * 2 = 1200 - 300 - 120.
def test_without_the_minimum_the_same_order_buys_60_chips():
    solution = solve_program(chip_planning(3, (order("order-1-1", "monitor", 60, 3),)))

    assert solution.value == pytest.approx(780)


# 90 * 20 - 100 * 4 - 90 * 2 + 10 * 1 = 1800 - 400 - 180 + 10, against
# 1800 - 90 * 5 - 180 = 1170 for 90 chips at the catalogue price.
def test_a_discount_from_100_chips_buys_100_for_an_order_of_90_monitors():
    planning = chip_planning(
        3,
        (order("order-1-1", "monitor", 90, 3),),
        tiers=(Tier(from_=Decimal(100), unit_price=Decimal(4)),),
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(1230)
    assert [buy.quantity for buy in solution.buys] == [pytest.approx(100)]


# 80 * 20 - 80 * 2 - 2 * 300: one changeover to each monitor in period 1, against
# 2 + 3 * 1 = 5 changeovers, 1500, when both are made in each of periods 1 to 4.
# The monitor the line is set for at the close may also be made later.
def test_changeovers_of_300_make_both_monitors_for_4_periods_at_once():
    orders = tuple(
        order(f"order-{period}-{monitor}", monitor, 10, period)
        for period in range(2, 6)
        for monitor in ("monitor-a", "monitor-b")
    )
    planning = chip_planning(
        5,
        orders,
        monitors=("monitor-a", "monitor-b"),
        changeover_cost=Decimal(300),
        chips_in_stock=Decimal(80),
    )

    solution = solve_program(planning, exact=True)

    assert solution.value == pytest.approx(840)
    assert sorted(produce.item for produce in solution.produces) == [
        "monitor-a",
        "monitor-b",
    ]


# A market split of 3 rows and 25 yes-or-no choices: each row holds a weight from 0
# to 99 drawn for every choice and asks the chosen weights to sum to half the weights
# of the row; the objective pays 1 for every unit over or under. Branch and bound
# closes it slowly, so the solve stops at its node limit with a solution and a gap
# above the gap limit, well within its time limit.
def market_split_program() -> Program:
    generator = random.Random(1)
    program = Program()
    choices = [program.add_binary(("choice", position)) for position in range(25)]
    for row in range(3):
        weights = [float(generator.randint(0, 99)) for _ in choices]
        over = program.add_variable(("over", row))
        under = program.add_variable(("under", row))
        terms = dict(zip(choices, weights, strict=True)) | {over: 1.0, under: -1.0}
        program.add_equal(Expression(terms=terms), float(sum(weights) // 2))
        program.objective.add(over, -1.0)
        program.objective.add(under, -1.0)
    return program


@pytest.mark.slow
def test_a_program_that_branch_and_bound_closes_slowly_stops_at_the_node_limit():
    values, value, solve = solve_integer(market_split_program(), 60.0, 1)

    assert values is not None
    assert value is not None
    assert solve.solution_found
    assert solve.stopped_at_node_limit
    assert not solve.stopped_at_time_limit
    assert solve.gap > GAP_LIMIT


@pytest.mark.parametrize(
    ("status", "message", "gap", "at_time_limit", "at_node_limit"),
    [
        (1, "Time limit reached.", 5.0, True, False),
        (4, SOLUTION_LIMIT, 0.25, False, True),
        (0, "Optimization terminated successfully.", 0.0, False, False),
    ],
)
def test_a_solve_with_a_solution_reports_its_gap_and_whether_it_stopped(
    status: int, message: str, gap: float, at_time_limit: bool, at_node_limit: bool
):
    result = result_of(
        status=status,
        x=np.zeros(2),
        fun=-10.0,
        mip_dual_bound=-10.0 - gap,
        message=message,
    )

    solve = read_integer_solve(result, 7)

    assert (
        solve.period,
        solve.solution_found,
        solve.stopped_at_time_limit,
        solve.stopped_at_node_limit,
        solve.value,
        solve.gap,
    ) == (7, True, at_time_limit, at_node_limit, 10.0, pytest.approx(gap))


@pytest.mark.parametrize(
    ("status", "message"), [(1, "Time limit reached."), (4, SOLUTION_LIMIT)]
)
def test_a_solve_stopped_at_a_limit_without_a_solution_reports_none_found(
    status: int, message: str
):
    solve = read_integer_solve(result_of(status=status, x=None, message=message), 7)

    assert (solve.solution_found, solve.value, solve.gap) == (False, None, math.inf)


def test_status_4_with_the_solution_limit_is_the_node_limit():
    solve = read_integer_solve(result_of(status=4, x=None, message=SOLUTION_LIMIT), 7)

    assert (solve.solution_found, solve.stopped_at_node_limit, solve.gap) == (
        False,
        True,
        math.inf,
    )


# scipy gives status 4 to the node limit of HiGHS, an interrupt and an unknown end
# alike; only the node limit is HiGHS status 16.
def test_status_4_with_a_solution_and_another_highs_status_is_not_the_node_limit():
    result = result_of(
        status=4, x=np.zeros(2), fun=-10.0, mip_dual_bound=-10.5, message=UNKNOWN
    )

    solve = read_integer_solve(result, 7)

    assert (
        solve.solution_found,
        solve.stopped_at_node_limit,
        solve.stopped_at_time_limit,
        solve.value,
        solve.gap,
    ) == (True, False, False, 10.0, 0.5)


def test_status_4_unbounded_or_infeasible_raises_an_error_naming_its_period():
    result = result_of(status=4, x=None, message=UNBOUNDED_OR_INFEASIBLE)

    with pytest.raises(RuntimeError, match="period 7"):
        read_integer_solve(result, 7)


def test_a_solve_without_a_solution_raises_an_error_naming_its_period():
    with pytest.raises(RuntimeError, match="period 7"):
        read_integer_solve(result_of(status=2, x=None), 7)


def test_a_program_with_no_feasible_solution_raises_an_error_naming_its_period():
    program = Program()
    chosen = program.add_binary(("order", "chip-maker", "chip", 7, False, "main"))
    program.add_at_most(Expression(terms={chosen: -1.0}), -2)

    with pytest.raises(RuntimeError, match="period 7"):
        solve_integer(program, 60.0, 7)


def test_a_fixed_program_without_an_optimum_raises_an_error_naming_its_period(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_linprog(_costs: np.ndarray, **_keys: object) -> OptimizeResult:
        return result_of(status=2, x=None, message="infeasible")

    monkeypatch.setattr(solve_module, "linprog", fake_linprog)
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    diagnostics: list[IntegerSolve | LinearSolve] = []

    with pytest.raises(RuntimeError, match=r"^period 1: "):
        solve_integer(program, 60.0, 1, diagnostics)

    assert isinstance(diagnostics[0], IntegerSolve)
    assert isinstance(diagnostics[1], LinearSolve)
    assert diagnostics[1].kind == "linear_fixed_binary"
    assert diagnostics[-1].status == 2


# 80 * 20 - 80 * 2 - 300: the item the line is set for needs no changeover.
@pytest.mark.parametrize(
    ("set_for", "made"),
    [
        ("monitor-a", ["monitor-a", "monitor-b"]),
        ("monitor-b", ["monitor-b", "monitor-a"]),
    ],
)
def test_a_line_makes_its_set_item_first_and_pays_one_changeover(
    set_for: str, made: list[str]
):
    orders = tuple(
        order(f"order-{period}-{monitor}", monitor, 10, period)
        for period in range(2, 6)
        for monitor in ("monitor-a", "monitor-b")
    )
    planning = chip_planning(
        5,
        orders,
        monitors=("monitor-a", "monitor-b"),
        changeover_cost=Decimal(300),
        chips_in_stock=Decimal(80),
    )
    planning = replace(
        planning, state=replace(planning.state, set_for={"line-1": set_for})
    )
    solution = solve_program(planning, exact=True)

    assert solution.value == pytest.approx(1140)
    produced = [
        decision["item"]
        for decision in decisions_json(solution, planning)
        if decision["kind"] == "produce"
    ]
    assert produced == made


def test_only_the_choices_of_the_first_period_are_binary():
    orders = (order("order-2-a", "monitor-a", 10, 2),)
    planning = chip_planning(
        3, orders, monitors=("monitor-a", "monitor-b"), changeover_cost=Decimal(300)
    )

    program = build_program(planning, with_rounding=False)

    binary = sorted(
        key for key, index in program.variables.items() if index in program.binaries
    )
    assert {key[-1] for key in binary} == {1}
    # The runs, set and changeover of each monitor, and the credit choice of the buy.
    assert len(binary) == 2 * 3 + 1


# The window of period 1 alone, of horizon 3, without customer orders, the buy of
# period 1 arriving in period 2: every chip bought is worth 2 at the end of the window,
# and no production of period 1 is worth its cost.
def credit_window(start_cash: Decimal) -> PlanningInput:
    planning = plain_tiny_planning()
    return replace(
        planning,
        window_end=1,
        starting_cash=start_cash,
        state=replace(planning.state, cash=start_cash),
        customer_orders=(),
        buy_options=planning.buy_options[:1],
        terminal_values={
            "chip": TerminalValue(value=Decimal(2), expected_use=Decimal(5000))
        },
    )


# The credit limit is 0: 1000 of headroom pays 2000 chips at 0.5, past the buy limit
# of 1000; 300 pays 600; -1000 and -10000001 pay none, and the program still has a
# solution.
@pytest.mark.parametrize(
    ("start_cash", "bought"),
    [
        (Decimal(1000), [Decimal("1000.000")]),
        (Decimal(300), [Decimal("600.000")]),
        (Decimal(-1000), []),
        (Decimal(-10000001), []),
    ],
)
def test_a_period_buys_only_within_the_credit_limit(
    start_cash: Decimal, bought: list[Decimal]
):
    planning = credit_window(start_cash)

    solution = solve_program(planning)

    assert solution.value is not None
    buys = [
        decision["quantity"]
        for decision in decisions_json(solution, planning)
        if decision["kind"] == "buy"
    ]
    assert buys == bought


# The chip at 1.0 and an open supplier order of 100 chips at 1.0 arriving in period 2,
# after the window: 1000 less the 100 owed pays 900 chips. Counting the order also as a
# payment of period 1 would leave 1000 - 100 - 100 = 800, and a buy at twice its price
# 400 chips.
def test_a_one_period_window_counts_an_arrival_after_it_once_in_its_credit_row():
    planning = credit_window(Decimal(1000))
    supplier_order = SupplierOrder(
        warehouse="main",
        material="chip",
        open_quantity=Decimal(100),
        unit_price=Decimal(1),
        arrivals=(Arrival(period=2, accepted=Decimal(100), left_open=ZERO),),
    )
    planning = replace(
        planning,
        state=replace(planning.state, supplier_orders=(supplier_order,)),
        buy_options=(replace(planning.buy_options[0], unit_price=Decimal(1)),),
    )

    solution = solve_program(planning)

    buys = [
        decision["quantity"]
        for decision in decisions_json(solution, planning)
        if decision["kind"] == "buy"
    ]
    assert buys == [Decimal("900.000")]


# No order, no stock, no rate and a credit limit of 0: the best plan places no decision
# and earns 0, however far the cash lies below the credit line.
@pytest.mark.parametrize(
    "start_cash", [Decimal(-9999999), Decimal(-10000000), Decimal(-10000001)]
)
def test_an_idle_window_far_below_the_credit_line_earns_0(start_cash: Decimal):
    planning = plain_tiny_planning()
    planning = replace(
        planning,
        starting_cash=start_cash,
        state=replace(planning.state, cash=start_cash, stock={"main": {}}),
        customer_orders=(),
    )

    solution = solve_program(planning)

    assert solution.value == pytest.approx(0)
    assert decisions_json(solution, planning) == []


@st.composite
def windows_below_the_credit_line(draw: st.DrawFn) -> PlanningInput:
    planning = plain_tiny_planning(draw(st.integers(min_value=1, max_value=4)))
    limit = draw(st.decimals(min_value=0, max_value=100000, places=4))
    rates = sorted(
        draw(
            st.lists(
                st.decimals(min_value=0, max_value="0.05", places=4),
                min_size=3,
                max_size=3,
            )
        )
    )
    cash = draw(st.decimals(min_value=-(10**9), max_value=-limit, places=4))
    stock = {
        item_id: draw(st.decimals(min_value=0, max_value=100, places=3))
        for item_id in ("chip", "board", "monitor")
    }
    owed = SupplierOrder(
        warehouse="main",
        material="chip",
        open_quantity=draw(st.decimals(min_value=0, max_value=1000, places=3)),
        unit_price=Decimal("0.5"),
        arrivals=(Arrival(period=2, accepted=Decimal(1), left_open=ZERO),),
    )
    return replace(
        planning,
        starting_cash=cash,
        cash=Cash(
            credit_limit=limit,
            credit_interest=rates[0],
            debit_interest=rates[1],
            overdraft_interest=rates[2],
        ),
        state=replace(
            planning.state, cash=cash, stock={"main": stock}, supplier_orders=(owed,)
        ),
    )


# Placing no buy is a plan of every window, so its buy options never lower the value
# of its program, however far the cash lies below the credit line.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(windows_below_the_credit_line())
def test_buy_options_never_lower_the_value_of_a_window_below_the_credit_line(
    planning: PlanningInput,
):
    with_buys = solve_program(planning)
    without_buys = solve_program(replace(planning, buy_options=())).value

    assert with_buys.value is not None
    assert with_buys.integer_solve is not None
    assert without_buys is not None
    assert with_buys.value >= without_buys - with_buys.integer_solve.gap - 1e-6


def test_only_a_period_with_a_buy_option_has_a_credit_choice():
    planning = plain_tiny_planning()

    program = build_program(planning, with_rounding=False)
    without_buys = build_program(replace(planning, buy_options=()), with_rounding=False)

    credit = {
        key: index for key, index in program.variables.items() if key[0] == "credit_ok"
    }
    assert list(credit) == [("credit_ok", 1), ("credit_ok", 2), ("credit_ok", 3)]
    assert [index in program.binaries for index in credit.values()] == [
        True,
        False,
        False,
    ]
    kinds = {str(key[0]) for key in program.variables}
    assert {kind for kind in kinds if kind.startswith("credit")} == {"credit_ok"}
    assert without_buys.binaries == set()
    assert not any(key[0] == "credit_ok" for key in without_buys.variables)


# The coefficients of `credit_ok` of a period in its two credit rows, as positive
# numbers: the largest cost of its buys, from the row of the cost of its buys, and the
# deficit bound, from the row of the credit limit.
def credit_bounds(planning: PlanningInput, period: int) -> tuple[float, float]:
    program = build_program(planning, with_rounding=False)
    choice = program.variables["credit_ok", period]
    coefficients = [
        terms[choice] for terms, _ in program.at_most_rows if choice in terms
    ]
    return -min(coefficients), max(coefficients)


# A second warehouse that accepts chips gives the chips of period 1 two buy variables,
# which share the buy limit of 1000: the buys cost at most 1000 * 0.5 = 500.
def test_a_buy_option_into_2_warehouses_counts_once_in_the_largest_cost_of_buys():
    planning = plain_tiny_planning()
    annex = Warehouse(
        capacity=Decimal(100),
        storage_factor=Decimal(1),
        transport_factor=Decimal(1),
        accepts=("chip",),
    )
    planning = replace(
        planning,
        warehouses={**planning.warehouses, "annex": annex},
        state=replace(
            planning.state, stock={**planning.state.stock, "annex": {"chip": ZERO}}
        ),
    )

    largest, _ = credit_bounds(planning, 1)

    assert largest == 500


# From cash -5000 a receivable of 3000 is paid in period 1, and at most 16 is spent
# before its buys: 8 boards of the 16 chips at 1 and 4 monitors of the 8 boards at 2.
# The lowest cash before the buys is -5000 + 3000 - 16 = -2016; nothing is owed and
# the credit limit is 0, so the deficit bound is 2016 and the margin 1.
def test_a_receivable_of_the_period_counts_in_the_lowest_cash_before_its_buys():
    planning = plain_tiny_planning()
    receivable = Receivable(amount=Decimal(3000), payment_period=1)
    planning = replace(
        planning,
        state=replace(planning.state, cash=Decimal(-5000), receivables=(receivable,)),
    )

    _, deficit = credit_bounds(planning, 1)

    assert deficit == 2017


# The plain tiny window has no minimum quantity, no discount tier and no changeover,
# yet its buy of period 1 makes it an integer program: the credit choice of period 1.
def test_a_plain_window_with_a_buy_in_its_first_period_is_an_integer_program():
    planning = plain_tiny_planning()

    program = build_program(planning, with_rounding=False)
    solution = solve_program(planning)

    assert {option.min_quantity for option in planning.buy_options} == {ZERO}
    assert {option.tiers for option in planning.buy_options} == {()}
    assert {
        (item.changeover_time, item.changeover_cost)
        for line in planning.lines.values()
        for item in line.items.values()
    } == {(ZERO, ZERO)}
    binary = [
        key for key, index in program.variables.items() if index in program.binaries
    ]
    assert binary == [("credit_ok", 1)]
    assert solution.integer_solve is not None


# Of the objective of 2 per order less the start cash of 1000, HiGHS reads the 2 per
# order only; the value adds the constant back.
def test_an_integer_solve_leaves_the_constant_of_the_objective_out_of_highs(
    monkeypatch: pytest.MonkeyPatch,
):
    sent: list[tuple[list[float], list[float], list[float]]] = []

    def fake_milp(costs: np.ndarray, **keys: object) -> OptimizeResult:
        bounds = cast(Bounds, keys["bounds"])
        sent.append((list(costs), list(bounds.lb), list(bounds.ub)))
        return result_of(status=0, x=np.ones(len(costs)), fun=-2.0, mip_dual_bound=-2.0)

    monkeypatch.setattr(solve_module, "milp", fake_milp)
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    program.objective = Expression(terms={0: 2.0}, constant=-1000.0)

    _, value, _ = solve_integer(program, 60.0, 1)

    assert sent == [([-2.0], [0.0], [1.0])]
    assert value == -998.0


def test_a_solve_called_infeasible_by_presolve_runs_once_more_within_its_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = [0.0]
    options: list[dict[str, object]] = []

    def fake_milp(costs: np.ndarray, **keys: object) -> OptimizeResult:
        clock[0] += 2.5
        options.append(cast(dict[str, object], keys["options"]))
        if len(options) == 1:
            return result_of(status=2, x=None)
        return result_of(status=0, x=np.ones(len(costs)), fun=-2.0, mip_dual_bound=-2.0)

    monkeypatch.setattr(solve_module, "milp", fake_milp)
    monkeypatch.setattr(
        solve_module, "time", SimpleNamespace(perf_counter=lambda: clock[0])
    )
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    program.objective = Expression(terms={0: 2.0})

    diagnostics: list[IntegerSolve | LinearSolve] = []
    _, value, _ = solve_integer(program, 60.0, 1, diagnostics)

    assert value == 2.0
    assert [record.status for record in diagnostics] == [2, 0, 0]
    # 60 less the reserve of 6, then less the 2.5 seconds of the first call too.
    assert options == [
        LIMITS | {"time_limit": 54.0},
        LIMITS | {"time_limit": 51.5, "presolve": False},
    ]


def test_a_solve_called_unbounded_or_infeasible_runs_once_more_within_its_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = [0.0]
    options: list[dict[str, object]] = []

    def fake_milp(costs: np.ndarray, **keys: object) -> OptimizeResult:
        clock[0] += 2.5
        options.append(cast(dict[str, object], keys["options"]))
        if len(options) == 1:
            return result_of(status=4, x=None, message=UNBOUNDED_OR_INFEASIBLE)
        return result_of(status=0, x=np.ones(len(costs)), fun=-2.0, mip_dual_bound=-2.0)

    monkeypatch.setattr(solve_module, "milp", fake_milp)
    monkeypatch.setattr(
        solve_module, "time", SimpleNamespace(perf_counter=lambda: clock[0])
    )
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    program.objective = Expression(terms={0: 2.0})

    _, value, _ = solve_integer(program, 60.0, 1)

    assert value == 2.0
    assert options == [
        LIMITS | {"time_limit": 54.0},
        LIMITS | {"time_limit": 51.5, "presolve": False},
    ]


# `milp` stops at the time limit with a solution worth 7 under a bound of 8, its
# binaries off 0 and 1 by its tolerance; the linear program with them fixed stops at
# its time limit too. The solve keeps the solution of `milp`, its binaries rounded, and
# the value 7 plus the constant 100.
def test_a_solve_stopped_at_its_time_limit_plays_the_solution_of_milp(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_milp(_costs: np.ndarray, **_keys: object) -> OptimizeResult:
        return result_of(
            status=1,
            x=np.array([0.9999999, 1e-7, 2.5]),
            fun=-7.0,
            mip_dual_bound=-8.0,
        )

    def fake_solve(
        _program: Program,
        _fixed: dict[int, float] | None = None,
        _time_limit: float | None = None,
    ) -> tuple[np.ndarray, float]:
        raise TimeoutError("Time limit reached")

    monkeypatch.setattr(solve_module, "milp", fake_milp)
    monkeypatch.setattr(solve_module, "_solve", fake_solve)
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    program.add_binary(("order", "chip-maker", "board", 1, False, "main"))
    program.add_variable(("buy", "chip-maker", "chip", 1, False, "main"))
    program.objective = Expression(terms={0: 2.0, 2: 2.0}, constant=100.0)

    values, value, solve = solve_integer(program, 60.0, 1)

    assert values is not None
    assert list(values) == [1.0, 0.0, 2.5]
    assert value == 107.0
    assert (
        solve.solution_found,
        solve.stopped_at_time_limit,
        solve.value,
        solve.bound,
        solve.gap,
    ) == (True, True, 107.0, 108.0, 1.0)


# `milp` takes all of its 54 seconds, 60 less the tenth of the budget held back; the
# linear program with the binaries fixed gets the 6 seconds left.
def test_the_linear_program_with_the_binaries_fixed_gets_the_reserve_of_the_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = [0.0]
    options: list[dict[str, float]] = []
    limits: list[float | None] = []

    def fake_milp(costs: np.ndarray, **keys: object) -> OptimizeResult:
        options.append(cast(dict[str, float], keys["options"]))
        clock[0] += options[-1]["time_limit"]
        return result_of(status=1, x=np.ones(len(costs)), fun=-2.0, mip_dual_bound=-3.0)

    def fake_solve(
        program: Program,
        _fixed: dict[int, float] | None = None,
        time_limit: float | None = None,
    ) -> tuple[np.ndarray, float]:
        limits.append(time_limit)
        return np.ones(len(program.upper_bounds)), 2.0

    monkeypatch.setattr(solve_module, "milp", fake_milp)
    monkeypatch.setattr(solve_module, "_solve", fake_solve)
    monkeypatch.setattr(
        solve_module, "time", SimpleNamespace(perf_counter=lambda: clock[0])
    )
    program = Program()
    program.add_binary(("order", "chip-maker", "chip", 1, False, "main"))
    program.objective = Expression(terms={0: 2.0})

    solve_integer(program, 60.0, 1)

    assert options == [LIMITS | {"time_limit": 54.0}]
    assert limits == [6.0]


# The world of a future minimum from period `first_period`: the plain tiny factory
# for 5 periods from an empty start, one order of 4 monitors due in period 5, no other
# demand, and chips of at least 20 at 0.5000, at 0.5500 in period 2.
def future_minimum_planning(first_period: int = 1) -> PlanningInput:
    planning = plain_tiny_planning(horizon=5)
    buy_options = tuple(
        replace(
            option,
            min_quantity=Decimal(20),
            unit_price=Decimal("0.55") if option.period == 2 else option.unit_price,
        )
        for option in planning.buy_options
        if option.period >= first_period
    )
    state = replace(
        planning.state,
        stock={"main": {"chip": ZERO, "board": ZERO, "monitor": ZERO}},
    )
    return replace(
        planning,
        first_period=first_period,
        state=state,
        customer_orders=(order("order-0-1", "monitor", 4, 5),),
        buy_options=buy_options,
    )


# The order of period 2 is a choice from 0 to 1, so 16 chips at 0.55 cost 8.8:
# 4 * 50 - 4 * 1 - 8 * 1 - 4 * 2 - 8.8.
def test_the_program_of_a_future_minimum_values_16_chips_of_period_2_at_171_2():
    solution = solve_program(future_minimum_planning())

    assert solution.value == pytest.approx(171.2)
    assert solution.buys == ()


# Every order is a whole choice: 20 chips at 0.5 in period 1 cost 10 and leave 4
# chips worth 0.1 each, against 20 at 0.55 in period 2: 180 - 10 + 0.4.
def test_the_exact_program_of_a_future_minimum_buys_20_chips_in_period_1_for_170_4():
    solution = solve_program(future_minimum_planning(), exact=True)

    assert solution.value == pytest.approx(170.4)
    assert [buy.quantity for buy in solution.buys] == [pytest.approx(20)]


# The order of period 2 is now whole: 20 chips at 0.55 cost 11 and leave 4 chips
# worth 0.1 each, 180 - 11 + 0.4.
def test_after_waiting_the_program_of_a_future_minimum_buys_20_chips_for_169_4():
    solution = solve_program(future_minimum_planning(first_period=2))

    assert solution.value == pytest.approx(169.4)
    assert [buy.quantity for buy in solution.buys] == [pytest.approx(20)]


def test_an_exact_program_of_more_than_100_binaries_is_refused():
    planning = plain_tiny_planning(horizon=51)
    buy_options = tuple(
        replace(option, min_quantity=Decimal(20)) for option in planning.buy_options
    )

    # An order choice and a credit choice in each of the 51 periods.
    with pytest.raises(ValueError, match="has 102 binary variables, above 100"):
        solve_program(replace(planning, buy_options=buy_options), exact=True)


# The world of an ordered transfer, one period of the plain tiny factory with no
# demand: `main` holds 2 chips of space 0.010 and the line, `buffer` takes materials
# only, `remote` holds 1 board of space 0.020 at a storage factor of 100, each of
# capacity 0.020, and a board costs 1 a period to store. The routes run in the order
# given, both free and of lead time 0.
def ordered_transfer_planning(routes: tuple[tuple[str, str], ...]) -> PlanningInput:
    planning = plain_tiny_planning(horizon=1)
    board = replace(planning.items["board"], storage_cost=Decimal(1))
    full = replace(planning.warehouses["main"], capacity=Decimal("0.020"))
    stock = {
        "main": {"chip": Decimal(2), "board": ZERO, "monitor": ZERO},
        "buffer": {"chip": ZERO},
        "remote": {"chip": ZERO, "board": Decimal(1), "monitor": ZERO},
    }
    return replace(
        planning,
        items={**planning.items, "board": board},
        warehouses={
            "main": full,
            "buffer": replace(full, accepts=("chip",)),
            "remote": replace(full, storage_factor=Decimal(100)),
        },
        routes=tuple(
            Route(source=source, destination=destination, cost=ZERO, lead_time=0)
            for source, destination in routes
        ),
        state=replace(planning.state, stock=stock),
        customer_orders=(),
        buy_options=(),
    )


# The buffer keeps a margin of 0.001 chips, so 1.999 chips leave main and free
# 0.01999 of space for 0.9995 boards. Stock is worth 2 * 0.1 + 0.5 = 0.7, and a
# board costs 1 a period in main and 100 in remote: 0.7 - 0.9995 - 0.0005 * 100.
def test_chips_sent_out_of_a_full_warehouse_free_the_space_of_a_board_sent_in():
    planning = ordered_transfer_planning((("main", "buffer"), ("remote", "main")))

    solution = solve_program(planning)

    assert [transfer.quantity for transfer in solution.transfers] == pytest.approx(
        [1.999, 0.9995]
    )
    assert solution.value == pytest.approx(-0.3495)


# The board would run first, into a main still full of chips, so it stays in
# remote: 0.7 - 100. Moving the chips alone gains nothing.
def test_a_board_sent_into_a_full_warehouse_before_its_chips_leave_never_moves():
    planning = ordered_transfer_planning((("remote", "main"), ("main", "buffer")))

    solution = solve_program(planning)

    assert [transfer.item for transfer in solution.transfers] in ([], ["chip"])
    assert solution.value == pytest.approx(-99.3)


# Each route runs into a full warehouse before the other frees it, so the board
# never leaves remote in either order: 0.7 - 100.
@pytest.mark.parametrize(
    "routes",
    [
        (("main", "remote"), ("remote", "main")),
        (("remote", "main"), ("main", "remote")),
    ],
)
def test_a_cyclic_swap_between_2_full_warehouses_stays_infeasible(
    routes: tuple[tuple[str, str], ...],
):
    planning = ordered_transfer_planning(routes)
    warehouses = {
        "main": planning.warehouses["main"],
        "remote": planning.warehouses["remote"],
    }
    stock = {key: planning.state.stock[key] for key in warehouses}

    solution = solve_program(
        replace(
            planning, warehouses=warehouses, state=replace(planning.state, stock=stock)
        )
    )

    assert solution.transfers == ()
    assert solution.value == pytest.approx(-99.3)


# The world of a large selling price with a buy limit of 1 chip: at a price of 10**15
# a ship earns 10**15 - 1 + 0.0001, and the program counts money in units of 10**7.
def test_a_price_of_10_to_15_ships_its_monitor_in_a_larger_unit_of_money():
    planning = solver_scale_planning(Decimal(10**15), buy_limit=Decimal(1))

    solution = solve_program(planning)

    assert decisions_json(solution, planning) == [
        {
            "kind": "ship",
            "order": "order-0-1",
            "quantity": Decimal("1.000"),
            "warehouse": "main",
        }
    ]
    assert solution.value is not None
    # A float near 10**15 has a step of 0.125, so each value is within 0.125 of it.
    assert abs(solution.value - 999999999999999.0001) <= 0.125
    assert abs(solve_relaxed(planning) - 999999999999999.0001) <= 0.125
    # The integer solve reports in money, its gap within the limit of 0.01 units of
    # money of 10**7.
    solve = solution.integer_solve
    assert solve is not None
    assert solve.value is not None
    assert abs(solve.value - 999999999999999.0001) <= 0.125
    assert 0 <= solve.gap <= GAP_LIMIT * 10**7
    fixed_solve = solve.fixed_binary_solve
    assert fixed_solve is not None
    assert fixed_solve.objective is not None
    assert abs(fixed_solve.objective - solve.value) <= 0.125

    relaxed_diagnostics: list[LinearSolve] = []
    relaxed_value = solve_relaxed(planning, relaxed_diagnostics)
    [relaxed_solve] = relaxed_diagnostics
    assert relaxed_solve.objective == pytest.approx(relaxed_value)


# The world of a large selling price: at 10**18 a ship earns
# 999999999999999999.0001, and money must be counted in units of 10**9. The cost of the
# buy limit of 0.001 chip at 0.5000, 0.0005, is then 5e-13, which HiGHS drops; the
# relaxed program has no credit row, and its smallest coefficient of money, the
# salvage value 0.1 of a chip, is then 1e-10.
@pytest.mark.parametrize(
    ("solve", "smallest", "in_units"),
    [(solve_program, "0.0005", "5e-13"), (solve_relaxed, "0.1", "1e-10")],
)
def test_a_price_of_10_to_18_beside_a_small_cost_is_outside_the_scale(
    solve: Callable[[PlanningInput], object], smallest: str, in_units: str
):
    planning = solver_scale_planning(Decimal(10**18))

    with pytest.raises(UnsupportedScaleError) as raised:
        solve(planning)

    assert str(raised.value) == (
        f"period 1: the money of the program runs from {smallest} to 1e+18; in "
        f"units of 1e+09 its smallest coefficient is {in_units}, at most 1e-09"
    )


# A ship pays the price less 1 of transport and saves the lost-sale penalty of 10, so
# at a price of 10**13 its coefficient of money is 10**13 + 9 and money is counted in
# units of 10**5. The cost 0.0005 of the buy limit stays above what HiGHS drops, at
# 5e-9: a ship earns 10**13 - 1 + 0.0001. At 10**14 the unit is 10**6 and the cost
# falls to 5e-10.
def test_a_cost_of_0_0005_beside_a_price_of_10_to_13_stays_in_the_program():
    planning = solver_scale_planning(Decimal(10**13))

    solution = solve_program(planning)

    assert [ship.quantity for ship in solution.ships] == [pytest.approx(1)]
    assert solution.value is not None
    # A float near 10**13 has a step of 0.002.
    assert abs(solution.value - 9999999999999.0001) <= 0.002
    with pytest.raises(UnsupportedScaleError, match=r"in units of 1e\+06 .* 5e-10,"):
        solve_program(solver_scale_planning(Decimal(10**14)))


# A receivable of 10**18 paid after the window is a constant of the objective only:
# money stays in units of 1, where a ship at the price of 50 earns 50 - 1 + 0.0001 and
# the chip salvage of 0.1 counts, and the value is 10**18 more.
def test_a_receivable_of_10_to_18_after_the_window_changes_no_decision():
    planning = replace(solver_scale_planning(Decimal(50)), buy_options=())
    receivable = Receivable(amount=Decimal(10**18), payment_period=2)
    planning = replace(
        planning, state=replace(planning.state, receivables=(receivable,))
    )

    solution = solve_program(planning)

    assert [ship.quantity for ship in solution.ships] == [pytest.approx(1)]
    assert solution.value is not None
    # A float near 10**18 has a step of 128.
    assert abs(solution.value - 1e18 - 49.0001) <= 128


# A warehouse of capacity 10**10 is a number of space that no unit of money brings
# down: its space row holds the capacity less the space of the stock, 0.15 of the
# monitor and 0.00001 of the chip.
def test_a_warehouse_of_capacity_10_to_10_is_outside_the_scale():
    planning = solver_scale_planning(Decimal(50))
    warehouse = replace(planning.warehouses["main"], capacity=Decimal(10**10))
    planning = replace(planning, warehouses={"main": warehouse})

    with pytest.raises(UnsupportedScaleError) as raised:
        solve_program(planning)

    assert str(raised.value) == (
        "period 1: a number of the program other than money is 1e+10, above 1e+09"
    )


# The planning input with every amount of money of the plain tiny factory times a
# factor: prices, costs, penalties, salvage values, cash and the credit limit.
def money_times(planning: PlanningInput, factor: Decimal) -> PlanningInput:
    items = {
        item_id: replace(
            item,
            storage_cost=item.storage_cost * factor,
            salvage_value=item.salvage_value * factor,
        )
        for item_id, item in planning.items.items()
    }
    lines = {
        line_id: replace(
            line,
            repair_cost=line.repair_cost * factor,
            overtime_cost=line.overtime_cost * factor,
            items={
                item_id: replace(line_item, cost=line_item.cost * factor)
                for item_id, line_item in line.items.items()
            },
        )
        for line_id, line in planning.lines.items()
    }
    customers = {
        customer_id: replace(
            customer,
            products={
                product_id: replace(
                    terms,
                    price=terms.price * factor,
                    transport_cost=terms.transport_cost * factor,
                    late_penalty=terms.late_penalty * factor,
                    lost_sale_penalty=terms.lost_sale_penalty * factor,
                )
                for product_id, terms in customer.products.items()
            },
        )
        for customer_id, customer in planning.customers.items()
    }
    return replace(
        planning,
        starting_cash=planning.starting_cash * factor,
        items=items,
        lines=lines,
        customers=customers,
        cash=replace(planning.cash, credit_limit=planning.cash.credit_limit * factor),
        state=replace(planning.state, cash=planning.state.cash * factor),
        buy_options=tuple(
            replace(option, unit_price=option.unit_price * factor)
            for option in planning.buy_options
        ),
    )


# Money times 10**k leaves the decisions of the plain tiny factory as they are and
# its value 10**k times as large, to a relative 1e-9, on the integer program with its
# buys and on the linear one without them. The ratios of its amounts stay those of
# units of 1, so the unit of money takes every factor up to 10**15.
@pytest.mark.property
@settings(max_examples=example_count(100))
@given(
    st.integers(min_value=0, max_value=15),
    st.integers(min_value=1, max_value=3),
    st.decimals(min_value=0, max_value=1000, places=4),
    st.booleans(),
)
def test_money_in_a_larger_unit_keeps_the_decisions_and_scales_the_value(
    exponent: int, horizon: int, credit_limit: Decimal, with_buys: bool
):
    planning = plain_tiny_planning(horizon)
    planning = replace(planning, cash=replace(planning.cash, credit_limit=credit_limit))
    if not with_buys:
        planning = replace(planning, buy_options=())
    scaled = money_times(planning, Decimal(10) ** exponent)

    solution = solve_program(planning)
    scaled_solution = solve_program(scaled)

    assert decisions_json(scaled_solution, scaled) == decisions_json(solution, planning)
    assert solution.value is not None and scaled_solution.value is not None
    assert scaled_solution.value == pytest.approx(
        solution.value * 10**exponent, rel=1e-9
    )
    assert solve_relaxed(scaled) == pytest.approx(
        solve_relaxed(planning) * 10**exponent, rel=1e-9
    )


# The world of a large selling price at a price of 10**k. Its money runs up to the
# coefficient of a ship, 10**k + 9, so from k = 9 it is counted in units of
# 10**(k - 8). The smallest coefficient of money is the cost 0.0005 of the buy limit
# of 0.001 chip, or the salvage value 0.1 of a chip with a buy limit of 1 or without
# a buy option, the linear program; it falls to 1e-9 or below from k = 14, or from
# k = 16. Below, a ship earns 10**k - 1 + 0.0001; from there, the program is outside
# the scale.
@pytest.mark.property
@settings(max_examples=example_count(100))
@given(
    st.integers(min_value=0, max_value=20),
    st.sampled_from([(Decimal("0.001"), 14), (Decimal(1), 16), (None, 16)]),
)
def test_a_price_outside_the_scale_is_named_and_one_within_it_ships(
    exponent: int, limit_and_first_unsupported: tuple[Decimal | None, int]
):
    buy_limit, first_unsupported = limit_and_first_unsupported
    planning = solver_scale_planning(Decimal(10**exponent), buy_limit or Decimal(1))
    if buy_limit is None:
        planning = replace(planning, buy_options=())

    if exponent >= first_unsupported:
        with pytest.raises(UnsupportedScaleError, match=r"^period 1: the money of"):
            solve_program(planning)
        return
    solution = solve_program(planning)

    assert [ship.quantity for ship in solution.ships] == [pytest.approx(1)]
    # Within one step of a float at the value, and at least 1e-6.
    step = max(math.ulp(10.0**exponent), 1e-6)
    assert abs(solution.value - (10**exponent - 0.9999)) <= step


def test_an_infinite_amount_of_money_is_outside_the_scale():
    program = Program()
    cash = program.add_variable(("cash_positive", 1))
    ship = program.add_variable(("ship", "order-1-1", "main", 1))
    program.add_equal(Expression(terms={cash: 1.0, ship: -math.inf}), 0.0, money=True)

    with pytest.raises(UnsupportedScaleError) as raised:
        build_money_unit(program, 3)

    assert str(raised.value) == "period 3: an amount of money of the program is inf"


# A knapsack of 150 choices and capacity 2540. An integer dynamic program over the
# capacity gives its optimum, 4787.
KNAPSACK_WEIGHTS = (
    50, 98, 54, 6, 34, 66, 63, 52, 39, 62, 46, 75, 28, 65, 18, 37, 18, 97, 13, 80,
    33, 69, 91, 78, 19, 40, 13, 94, 10, 88, 43, 61, 72, 13, 46, 56, 41, 79, 82, 27,
    71, 62, 57, 67, 34, 8, 71, 2, 12, 93, 52, 91, 86, 81, 1, 79, 64, 43, 32, 94,
    42, 91, 9, 25, 73, 29, 31, 19, 70, 58, 12, 11, 41, 66, 63, 14, 39, 71, 38, 91,
    16, 71, 43, 70, 27, 78, 71, 76, 37, 57, 12, 77, 50, 41, 74, 31, 38, 24, 25, 24,
    5, 79, 85, 34, 61, 9, 12, 87, 97, 17, 20, 5, 11, 90, 70, 88, 51, 91, 68, 36,
    67, 31, 28, 87, 76, 54, 75, 36, 58, 64, 85, 83, 90, 46, 11, 42, 79, 15, 63, 76,
    81, 43, 25, 32, 3, 94, 35, 15, 91, 29,
)  # fmt: skip
KNAPSACK_VALUES = (
    48, 22, 43, 55, 8, 13, 19, 90, 29, 6, 74, 82, 69, 78, 88, 10, 4, 16, 82, 25,
    78, 74, 16, 51, 12, 48, 15, 5, 78, 3, 25, 24, 92, 16, 62, 27, 94, 8, 87, 3,
    70, 55, 80, 13, 34, 9, 29, 10, 83, 39, 45, 56, 24, 8, 65, 60, 6, 77, 13, 90,
    51, 26, 34, 46, 94, 61, 73, 22, 90, 87, 27, 99, 8, 87, 21, 21, 44, 68, 33, 16,
    77, 57, 86, 23, 2, 61, 88, 53, 73, 66, 40, 84, 46, 50, 85, 33, 20, 72, 89, 2,
    59, 95, 11, 43, 95, 6, 70, 36, 18, 31, 98, 62, 46, 79, 37, 87, 46, 76, 82, 80,
    17, 92, 40, 50, 96, 54, 84, 11, 1, 77, 25, 90, 43, 21, 31, 29, 82, 58, 49, 91,
    87, 73, 54, 5, 52, 90, 73, 54, 99, 85,
)  # fmt: skip
KNAPSACK_CAPACITY = 2540
KNAPSACK_OPTIMUM = 4787


# A program that chooses which of the items to take, within the capacity, with the
# objective of the values taken plus a constant.
def knapsack_program(
    weights: tuple[int, ...], values: tuple[int, ...], capacity: int, constant: float
) -> Program:
    program = Program()
    chosen = [
        program.add_binary(("choice", position)) for position in range(len(weights))
    ]
    program.add_at_most(
        Expression(terms=dict(zip(chosen, map(float, weights), strict=True))),
        float(capacity),
    )
    program.objective = Expression(
        terms=dict(zip(chosen, map(float, values), strict=True)), constant=constant
    )
    return program


def taken_value(values: tuple[int, ...], solution: np.ndarray) -> int:
    return sum(
        value for value, taken in zip(values, solution, strict=False) if taken > 0.5
    )


# A constant of the objective changes no decision: the solve takes 4787 with every
# constant, its value is 4787 plus the constant, and its gap is within the limit. A
# constant of 10**20 lies beyond the costs HiGHS reads, 1e20 and more being infinite.
@pytest.mark.parametrize("constant", [0, 10**9, -(10**9), 10**20])
def test_a_constant_of_the_objective_leaves_the_knapsack_at_its_optimum(
    constant: int,
):
    program = knapsack_program(
        KNAPSACK_WEIGHTS, KNAPSACK_VALUES, KNAPSACK_CAPACITY, float(constant)
    )

    solution, value, solve = solve_integer(program, 60.0, 1)

    assert solution is not None
    assert taken_value(KNAPSACK_VALUES, solution) == KNAPSACK_OPTIMUM
    assert value == pytest.approx(KNAPSACK_OPTIMUM + constant, abs=1e-6)
    assert solve.value == pytest.approx(KNAPSACK_OPTIMUM + constant, abs=1e-6)
    assert solve.value is not None
    assert solve.bound is not None
    assert 0 <= solve.gap == pytest.approx(solve.bound - solve.value, abs=1e-6)
    assert solve.gap <= GAP_LIMIT


# Cash carried into a window is a variable that its rows fix, as the cash a later
# period starts from holds the profit of the periods before it. It changes no decision.
@pytest.mark.parametrize("carried", [0, 10**9])
def test_cash_carried_in_its_rows_leaves_the_knapsack_at_its_optimum(carried: int):
    program = knapsack_program(
        KNAPSACK_WEIGHTS, KNAPSACK_VALUES, KNAPSACK_CAPACITY, -float(carried)
    )
    cash = program.add_variable(("cash_positive", 1))
    program.add_equal(Expression(terms={cash: 1.0}), float(carried))
    program.objective.add(cash, 1.0)

    solution, value, _ = solve_integer(program, 60.0, 1)

    assert solution is not None
    assert taken_value(KNAPSACK_VALUES, solution) == KNAPSACK_OPTIMUM
    assert value == pytest.approx(KNAPSACK_OPTIMUM, abs=1e-6)


# The knapsack solved with the constant 10**9 inside the objective of HiGHS stops at
# 4708 under a bound of 4788, a relative gap of 8e-8 of the whole objective. The gap
# of the solve is 80, the most it can lose: it loses 79 against the optimum of 4787.
def test_a_solve_reports_the_value_and_bound_of_its_program_and_their_gap():
    result = result_of(
        status=0,
        x=np.zeros(2),
        fun=-1000004708.0,
        mip_dual_bound=-1000004788.0,
        mip_gap=7.999962336177321e-08,
    )

    solve = read_integer_solve(result, 1)

    assert (solve.value, solve.bound, solve.gap) == (1000004708.0, 1000004788.0, 80.0)
    assert solve.gap >= 10**9 + KNAPSACK_OPTIMUM - 1000004708.0 == 79


# A result of HiGHS for the program of period 2 of a world of the plain tiny factory:
# optimal, with its bound one rounding of floating point below the value of its
# solution.
def test_a_bound_one_rounding_below_the_value_is_a_gap_of_0():
    result = result_of(
        status=0, x=np.zeros(2), fun=-182.4, mip_dual_bound=-182.39999999999998
    )

    solve = read_integer_solve(result, 2)

    assert (solve.value, solve.bound, solve.gap) == (182.4, 182.39999999999998, 0.0)


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(money_values, money_values)
@example(-182.4, -182.39999999999998)
def test_the_gap_of_a_solve_with_a_solution_is_at_least_0(
    costs: float, dual_bound: float
):
    result = result_of(status=0, x=np.zeros(2), fun=costs, mip_dual_bound=dual_bound)

    solve = read_integer_solve(result, 1)

    assert solve.gap >= 0
    if dual_bound <= costs:
        assert solve.gap == costs - dual_bound


def knapsack_optimum(
    weights: tuple[int, ...], values: tuple[int, ...], capacity: int
) -> int:
    best = [0] * (capacity + 1)
    for weight, value in zip(weights, values, strict=True):
        for room in range(capacity, weight - 1, -1):
            best[room] = max(best[room], best[room - weight] + value)
    return best[capacity]


@st.composite
def knapsacks(draw: st.DrawFn) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    count = draw(st.integers(min_value=1, max_value=40))
    weights = tuple(
        draw(
            st.lists(
                st.integers(min_value=1, max_value=100), min_size=count, max_size=count
            )
        )
    )
    values = tuple(
        draw(
            st.lists(
                st.integers(min_value=1, max_value=100), min_size=count, max_size=count
            )
        )
    )
    return weights, values, draw(st.integers(min_value=0, max_value=sum(weights)))


# A constant of the objective, and cash carried in the rows, change only the value of
# every solution alike. The solve then takes a solution within the gap limit of the
# optimum that the dynamic program gives, and reports a gap within the limit.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    knapsacks(),
    st.integers(min_value=-(10**15), max_value=10**15),
    st.integers(min_value=0, max_value=10**9),
)
def test_an_offset_of_the_objective_keeps_the_solve_within_its_gap_limit(
    knapsack: tuple[tuple[int, ...], tuple[int, ...], int], constant: int, carried: int
):
    weights, values, capacity = knapsack
    program = knapsack_program(weights, values, capacity, float(constant - carried))
    cash = program.add_variable(("cash_positive", 1))
    program.add_equal(Expression(terms={cash: 1.0}), float(carried))
    program.objective.add(cash, 1.0)
    optimum = knapsack_optimum(weights, values, capacity)

    solution, value, solve = solve_integer(program, 60.0, 1)

    assert solution is not None
    assert taken_value(values, solution) >= optimum - GAP_LIMIT
    assert value is not None
    # The value of the solution taken, within one step of a float at the constant.
    step = max(math.ulp(float(abs(constant) + sum(values))), 1e-6)
    assert abs(value - (taken_value(values, solution) + constant)) <= step
    assert solve.gap <= GAP_LIMIT


# A knapsack whose every choice has a part of up to one more unit beside it, of the same
# weight and value, so that the linear program with the binaries fixed has variables
# left. Time limits from 0.001 to 1 second, drawn on a log scale, stop `milp` or that
# linear program at their limit. Whenever `milp` ends with a solution, the solve plays
# it, and the whole solve ends within its time limit and the overhead of one call.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    knapsacks(),
    st.floats(min_value=-3.0, max_value=0.0).map(lambda exponent: 10.0**exponent),
)
def test_a_solve_with_a_solution_of_milp_plays_it_within_its_time_limit(
    knapsack: tuple[tuple[int, ...], tuple[int, ...], int], time_limit: float
):
    weights, values, capacity = knapsack
    program = Program()
    row = Expression()
    for position, (weight, value) in enumerate(zip(weights, values, strict=True)):
        chosen = program.add_binary(("choice", position))
        part = program.add_variable(("part", position), 1.0)
        for variable in (chosen, part):
            row.add(variable, float(weight))
            program.objective.add(variable, float(value))
    program.add_at_most(row, float(capacity))
    results: list[OptimizeResult] = []
    real_milp = cast(Callable[..., OptimizeResult], solve_module.milp)

    def recorded_milp(costs: np.ndarray, **keys: object) -> OptimizeResult:
        result = real_milp(costs, **keys)
        results.append(result)
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(solve_module, "milp", recorded_milp)
        solution, value, solve = solve_integer(program, time_limit, 1)

    if results[-1].get("x") is not None:
        assert solution is not None
        assert value is not None
        assert solve.solution_found
    assert solve.seconds <= time_limit + CALL_OVERHEAD
