from dataclasses import replace
from decimal import ROUND_CEILING, Decimal
from typing import Any

import pytest
from factories import example_count, plain_tiny_planning
from hypothesis import example, given, settings
from hypothesis import strategies as st

from factory_simulator.benchmark.client import Check
from factory_simulator.benchmark.models.inputs import (
    Hours,
    Item,
    LineItem,
    PlanningInput,
    Tier,
)
from factory_simulator.benchmark.models.outputs import (
    IntegerSolve,
    LinearSolve,
    Solution,
    SolutionBuy,
    SolutionProduce,
    SolutionShip,
)
from factory_simulator.benchmark.program.decisions import (
    QUANTITY_EXPONENT,
    Optimizer,
    changeover_order,
    check_and_fit,
    decide_by_program,
    decisions_json,
    fit_rejected,
    fitted_quantities,
    is_within_space,
    order_produces,
    paid_changeovers,
    planned_changeovers,
    played_changeovers,
    produce_decision,
    round_down,
    space_added,
    space_change,
    space_left_for_produces,
    unit_space,
)
from factory_simulator.benchmark.program.solve import solve_program

PRODUCE: dict[str, Any] = {
    "kind": "produce",
    "item": "board",
    "recipe": "standard",
    "quantity": Decimal("10.000"),
}
SHORT: dict[str, Any] = {
    "decision_id": "2-1",
    "accepted": False,
    "reason": "not_enough_input",
    "item": "chip",
    "asked": Decimal("20.000"),
    "available": Decimal("19.995"),
}
ACCEPTED: dict[str, Any] = {"decision_id": "2-1", "accepted": True}


def solution_of(
    ships: tuple[SolutionShip, ...] = (),
    produces: tuple[SolutionProduce, ...] = (),
    buys: tuple[SolutionBuy, ...] = (),
) -> Solution:
    return Solution(
        value=0.0, ships=ships, transfers=(), repairs=(), produces=produces, buys=buys
    )


# The plain tiny planning input whose chips of period 1 cost `price` per unit, with
# a minimum quantity and discount tiers.
def chip_planning(
    price: str, min_quantity: str = "0", tiers: tuple[Tier, ...] = ()
) -> PlanningInput:
    planning = plain_tiny_planning()
    first = replace(
        planning.buy_options[0],
        unit_price=Decimal(price),
        min_quantity=Decimal(min_quantity),
        tiers=tiers,
    )
    return replace(planning, buy_options=(first, *planning.buy_options[1:]))


# A buy of chips into the main warehouse.
def chip_buy(quantity: str, supplier: str = "chip-maker") -> dict[str, Any]:
    return {
        "kind": "buy",
        "supplier": supplier,
        "material": "chip",
        "quantity": Decimal(quantity),
        "warehouse": "main",
        "express": False,
    }


# The outcome of the decision at a position of period 1 rejected for its credit.
def over_credit(position: int, asked: str, available: str) -> dict[str, Any]:
    return {
        "decision_id": f"1-{position}",
        "accepted": False,
        "reason": "over_credit_limit",
        "asked": Decimal(asked),
        "available": Decimal(available),
    }


def test_a_buy_below_a_thousandth_gives_no_decision():
    buy = SolutionBuy(
        supplier="chip-maker",
        material="chip",
        warehouse="main",
        express=False,
        quantity=0.0004,
    )

    assert decisions_json(solution_of(buys=(buy,)), plain_tiny_planning()) == []


def test_a_solution_lists_its_ship_then_its_produce_then_its_buy():
    buy = SolutionBuy(
        supplier="chip-maker",
        material="chip",
        warehouse="main",
        express=True,
        quantity=10.0,
    )
    ship = SolutionShip(order="order-1-1", warehouse="main", quantity=4.0)
    produce = SolutionProduce(
        line="line-1", item="monitor", recipe="standard", overtime=False, quantity=2.5
    )

    decisions = decisions_json(
        solution_of((ship,), (produce,), (buy,)), plain_tiny_planning()
    )

    assert decisions == [
        {
            "kind": "ship",
            "order": "order-1-1",
            "quantity": Decimal("4.000"),
            "warehouse": "main",
        },
        {
            "kind": "produce",
            "line": "line-1",
            "item": "monitor",
            "quantity": Decimal("2.500"),
            "recipe": "standard",
            "overtime": False,
        },
        {
            "kind": "buy",
            "supplier": "chip-maker",
            "material": "chip",
            "quantity": Decimal("10.000"),
            "warehouse": "main",
            "express": True,
        },
    ]


def test_a_buy_beyond_the_credit_limit_shrinks_to_what_is_available():
    # 10 units ask 100.0000 against 99.9500: 10 * 99.95 / 100 = 9.995 units.
    planning = chip_planning("10.0000")
    buy = chip_buy("10.000")

    assert fit_rejected([buy], [over_credit(1, "100.0000", "99.9500")], planning) == [
        chip_buy("9.995")
    ]
    assert fit_rejected([buy], [over_credit(1, "0.0000", "-5.0000")], planning) == []


def test_a_buy_fitted_below_its_minimum_quantity_is_left_out():
    # 10 * 4.9975 / 5 = 9.995 units, below the minimum of 10.
    planning = chip_planning("0.5000", min_quantity="10.000")
    outcome = over_credit(1, "5.0000", "4.9975")

    assert fit_rejected([chip_buy("10.000")], [outcome], planning) == []


def test_a_buy_fitted_to_its_minimum_quantity_is_kept():
    # 12 * 5 / 6 = 10 units, the minimum.
    planning = chip_planning("0.5000", min_quantity="10.000")
    outcome = over_credit(1, "6.0000", "5.0000")

    assert fit_rejected([chip_buy("12.000")], [outcome], planning) == [
        chip_buy("10.000")
    ]


def test_a_buy_fitted_below_the_tier_it_was_priced_at_is_left_out():
    # 1200 * 4500 / 5520 = 978.260 units, below the tier from 1000.
    tier = Tier(from_=Decimal("1000.000"), unit_price=Decimal("4.6000"))
    planning = chip_planning("5.0000", tiers=(tier,))
    outcome = over_credit(1, "5520.0000", "4500.0000")

    assert fit_rejected([chip_buy("1200.000")], [outcome], planning) == []


def test_buys_beyond_the_credit_limit_share_the_money_available():
    # The first buy takes the 6.0000 available, 6 units; 6.0000 - 6.000 * 1.0000 = 0
    # is left for the second.
    planning = chip_planning("1.0000")
    second = replace(planning.buy_options[0], supplier="other-chip-maker")
    planning = replace(planning, buy_options=(*planning.buy_options, second))
    buys = [chip_buy("10.000"), chip_buy("10.000", "other-chip-maker")]
    outcomes = [
        over_credit(1, "10.0000", "6.0000"),
        over_credit(2, "10.0000", "6.0000"),
    ]

    assert fit_rejected(buys, outcomes, planning) == [chip_buy("6.000")]


# A buy of 12 chips with a minimum of 10 asks 6.0000 against 4.9975: the 9.995 chips
# the money pays for are below its minimum, so it is left out and uses no money. The
# buy of the other chip maker, without a minimum, then gets 4.9975 / 0.5 = 9.995.
def test_a_buy_left_out_below_its_minimum_leaves_its_money_to_the_next_buy():
    planning = chip_planning("0.5000", min_quantity="10.000")
    second = replace(
        planning.buy_options[0], supplier="other-chip-maker", min_quantity=Decimal(0)
    )
    planning = replace(planning, buy_options=(*planning.buy_options, second))
    buys = [chip_buy("12.000"), chip_buy("10.000", "other-chip-maker")]
    outcomes = [
        over_credit(1, "6.0000", "4.9975"),
        over_credit(2, "5.0000", "4.9975"),
    ]

    assert fit_rejected(buys, outcomes, planning) == [
        chip_buy("9.995", "other-chip-maker")
    ]


# A check of buys as step 5 checks them, in order: a buy adds its chips times 0.01
# of space and costs its chips times its unit price; one beyond the space left is
# rejected for space, one beyond the cash left for its credit, and an accepted one
# takes both.
def buy_check(space: str, cash: str, planning: PlanningInput) -> Check:
    def check(period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        space_left, cash_left = Decimal(space), Decimal(cash)
        outcomes: list[dict[str, Any]] = []
        for position, decision in enumerate(decisions, 1):
            outcome = {"decision_id": f"{period}-{position}", "accepted": False}
            option = next(
                option
                for option in planning.buy_options
                if option.supplier == decision["supplier"] and option.period == period
            )
            added = decision["quantity"] * Decimal("0.01")
            cost = decision["quantity"] * option.unit_price
            if added > space_left:
                outcome |= {
                    "reason": "not_enough_space",
                    "asked": added,
                    "available": space_left,
                }
            elif cost > cash_left:
                outcome |= {
                    "reason": "over_credit_limit",
                    "asked": cost,
                    "available": cash_left,
                }
            else:
                outcome["accepted"] = True
                space_left -= added
                cash_left -= cost
            outcomes.append(outcome)
        return outcomes

    return check


# The buy of 12 chips with a minimum of 10 asks 6.0000 against 4.9975 and is left
# out; the buy of the other chip maker takes its position and is checked again: its
# 10 chips ask 5.0000 against 4.9975, so it is fitted to 9.995.
def test_a_buy_after_one_fitted_to_0_takes_its_position_and_is_fitted():
    planning = chip_planning("0.5000", min_quantity="10.000")
    second = replace(
        planning.buy_options[0], supplier="other-chip-maker", min_quantity=Decimal(0)
    )
    planning = replace(planning, buy_options=(*planning.buy_options, second))
    buys = [chip_buy("12.000"), chip_buy("10.000", "other-chip-maker")]

    accepted, dropped, fitted = check_and_fit(
        buy_check("100", "4.9975", planning), buys, planning
    )

    assert accepted == [chip_buy("9.995", "other-chip-maker")]
    assert dropped == []
    assert [(entry["reason"], entry["before"], entry["after"]) for entry in fitted] == [
        ("over_credit_limit", Decimal("12.000"), Decimal("0")),
        ("over_credit_limit", Decimal("10.000"), Decimal("9.995")),
    ]


# A buy of 100 chips adds 1.00 of space against 0.50 free, so the fit takes
# (1.00 - 0.50) / 0.01 = 50 chips; the 50 left cost 25.0000 against 20.0000 of cash,
# so the fit for its credit keeps 20 / 0.5 = 40, which fits both.
def test_a_buy_fitted_for_space_and_then_rejected_for_its_credit_is_fitted_again():
    planning = chip_planning("0.5000")

    accepted, dropped, fitted = check_and_fit(
        buy_check("0.50", "20.0000", planning), [chip_buy("100.000")], planning
    )

    assert accepted == [chip_buy("40.000")]
    assert dropped == []
    assert [(entry["reason"], entry["before"], entry["after"]) for entry in fitted] == [
        ("not_enough_space", Decimal("100.000"), Decimal("50.000")),
        ("over_credit_limit", Decimal("50.000"), Decimal("40.000")),
    ]


# The first check finds 0.005 chip short of 10 boards of 2 chips each, so the
# production becomes 19.995 / 2 = 9.9975, rounded down to 9.997, and is checked again.
def test_a_decision_a_check_rejects_is_fitted_and_checked_again():
    answers = [[SHORT], [ACCEPTED]]
    checked: list[tuple[int, list[dict[str, Any]]]] = []

    def check(period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checked.append((period, decisions))
        return answers[len(checked) - 1]

    planning = replace(plain_tiny_planning(), first_period=2)
    history: list[dict[str, Any]] = []

    accepted, dropped, fitted = check_and_fit(check, [PRODUCE], planning, history)

    fitted_produce = PRODUCE | {"quantity": Decimal("9.997")}
    assert accepted == [fitted_produce]
    assert dropped == []
    assert fitted == [
        {
            "period": 2,
            "decision": PRODUCE,
            "reason": "not_enough_input",
            "before": Decimal("10.000"),
            "after": Decimal("9.997"),
        }
    ]
    assert checked == [(2, [PRODUCE]), (2, [fitted_produce])]
    assert [entry["decisions"] for entry in history] == [
        [PRODUCE],
        [fitted_produce],
    ]
    assert [entry["outcomes"] for entry in history] == answers


# A transfer of chips to a full warehouse is short of 0.001 of space, and a production
# of monitors, which needs the space the transfer frees, is rejected with it. The fit
# takes 0.001 / 0.01 = 0.1 chip from the transfer and checks again; the production
# then passes as planned.
def test_a_decision_rejected_after_an_earlier_rejection_is_checked_again_unfitted():
    transfer = {
        "kind": "transfer",
        "item": "chip",
        "quantity": Decimal("10.000"),
        "source": "main",
        "destination": "centre",
    }
    produce = {
        "kind": "produce",
        "line": "line-1",
        "item": "monitor",
        "quantity": Decimal("5.000"),
        "recipe": "standard",
        "overtime": False,
    }
    short = {"accepted": False, "reason": "not_enough_space"}
    answers = [
        [
            short
            | {
                "decision_id": "1-1",
                "asked": Decimal("0.101"),
                "available": Decimal("0.100"),
            },
            short
            | {
                "decision_id": "1-2",
                "asked": Decimal("0.55"),
                "available": Decimal("0.001"),
            },
        ],
        [
            {"decision_id": "1-1", "accepted": True},
            {"decision_id": "1-2", "accepted": True},
        ],
    ]
    checked: list[list[dict[str, Any]]] = []

    def check(_period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checked.append(decisions)
        return answers[len(checked) - 1]

    accepted, dropped, fitted = check_and_fit(
        check, [transfer, produce], plain_tiny_planning()
    )

    fitted_transfer = transfer | {"quantity": Decimal("9.900")}
    assert accepted == [fitted_transfer, produce]
    assert dropped == []
    assert [(entry["decision"], entry["after"]) for entry in fitted] == [
        (transfer, Decimal("9.900"))
    ]
    assert len(checked) == 2


# A check of productions as step 5 checks their inputs: each takes its inputs,
# rounded up to 3 places, from `stock`, and the first input short, in the order of
# the identifiers, rejects it.
def input_check(stock: dict[str, Decimal], planning: PlanningInput) -> Check:
    def check(period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        left = dict(stock)
        outcomes: list[dict[str, Any]] = []
        for position, decision in enumerate(decisions, 1):
            recipe = planning.items[decision["item"]].recipes[decision["recipe"]]
            needed = {
                input_id: (decision["quantity"] * per_unit).quantize(
                    QUANTITY_EXPONENT, ROUND_CEILING
                )
                for input_id, per_unit in sorted(recipe.items())
            }
            short = [
                input_id for input_id in needed if needed[input_id] > left[input_id]
            ]
            outcome: dict[str, Any] = {"decision_id": f"{period}-{position}"}
            if short:
                outcome |= {
                    "accepted": False,
                    "reason": "not_enough_input",
                    "item": short[0],
                    "asked": needed[short[0]],
                    "available": left[short[0]],
                }
            else:
                outcome |= {"accepted": True}
                for input_id, units in needed.items():
                    left[input_id] -= units
            outcomes.append(outcome)
        return outcomes

    return check


# The plain tiny planning input whose monitor takes the inputs of `recipe` per unit.
def monitor_planning(recipe: dict[str, Decimal]) -> PlanningInput:
    planning = plain_tiny_planning()
    monitor = replace(planning.items["monitor"], recipes={"standard": recipe})
    return replace(planning, items={**planning.items, "monitor": monitor})


def produce_monitors(quantity: Decimal) -> dict[str, Any]:
    return {
        "kind": "produce",
        "line": "line-1",
        "item": "monitor",
        "quantity": quantity,
        "recipe": "standard",
        "overtime": False,
    }


# 10 monitors of one board and one chip each with 5 boards and 2 chips in stock: the
# check names the boards first, then the chips; 2 monitors take what both allow.
def test_a_production_short_of_2_inputs_keeps_what_both_allow():
    planning = monitor_planning({"board": Decimal(1), "chip": Decimal(1)})
    check = input_check({"board": Decimal(5), "chip": Decimal(2)}, planning)

    accepted, dropped, _ = check_and_fit(
        check, [produce_monitors(Decimal("10.000"))], planning
    )

    assert accepted == [produce_monitors(Decimal("2.000"))]
    assert dropped == []


@st.composite
def short_productions(
    draw: st.DrawFn,
) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
    quantity = draw(st.decimals(min_value="0.001", max_value=1000, places=3))
    count = draw(st.integers(min_value=1, max_value=3))
    recipe: dict[str, Decimal] = {}
    stock: dict[str, Decimal] = {}
    for position in range(1, count + 1):
        per_unit = draw(st.decimals(min_value="0.001", max_value=5, places=3))
        needed = quantity * per_unit
        recipe[f"input-{position}"] = per_unit
        stock[f"input-{position}"] = draw(
            st.decimals(min_value=0, max_value=needed * 2, places=3)
        )
    return quantity, recipe, stock


# The quantity accepted takes no more of any input than it has in stock, and a
# thousandth more would take more of one, unless it is the quantity asked.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(short_productions())
def test_a_production_short_of_its_inputs_keeps_the_most_every_input_allows(
    production: tuple[Decimal, dict[str, Decimal], dict[str, Decimal]],
):
    quantity, recipe, stock = production
    planning = monitor_planning(recipe)
    check = input_check(stock, planning)

    accepted, _, _ = check_and_fit(check, [produce_monitors(quantity)], planning)

    kept = accepted[0]["quantity"] if accepted else Decimal(0)

    def allowed(made: Decimal) -> bool:
        return all(
            (made * per_unit).quantize(QUANTITY_EXPONENT, ROUND_CEILING)
            <= stock[input_id]
            for input_id, per_unit in recipe.items()
        )

    assert allowed(kept)
    assert kept == quantity or not allowed(kept + QUANTITY_EXPONENT)


def test_decisions_a_check_accepts_are_checked_once():
    checked: list[list[dict[str, Any]]] = []

    def check(_period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checked.append(decisions)
        return [ACCEPTED]

    planning = replace(plain_tiny_planning(), first_period=2)

    assert check_and_fit(check, [PRODUCE], planning) == ([PRODUCE], [], [])
    assert len(checked) == 1


# A check that accepts every decision of a period.
def accept_all(period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"decision_id": f"{period}-{position}", "accepted": True}
        for position in range(1, len(decisions) + 1)
    ]


# The plain tiny planning input whose line makes boards and monitors with a
# changeover time of 1 hour each.
def changeover_planning() -> PlanningInput:
    planning = plain_tiny_planning()
    line = planning.lines["line-1"]
    items = {
        item_id: replace(item, changeover_time=Decimal(1))
        for item_id, item in line.items.items()
    }
    return replace(planning, lines={"line-1": replace(line, items=items)})


# The program of the plain tiny factory makes 8 boards and 4 monitors and is worth
# 328 (`test_solve.py`); its relaxed program has the same value.
def test_an_optimizer_of_the_plain_tiny_factory_makes_boards_then_monitors():
    planning = plain_tiny_planning()
    optimizer = Optimizer(
        planning_source=lambda description, observation: planning, check=accept_all
    )

    decisions = optimizer({}, {})

    assert [decision["item"] for decision in decisions] == ["board", "monitor"]
    assert optimizer.relaxed_program_value == pytest.approx(328)


def test_an_optimizer_retains_the_inputs_plan_check_and_fitted_submission():
    planning = plain_tiny_planning()
    description = {"run": "r-1"}
    observation = {"period": 1, "cash": "1000"}
    optimizer = Optimizer(
        planning_source=lambda seen_description, seen_observation: planning,
        check=accept_all,
    )

    submitted = optimizer(description, observation)

    [period] = optimizer.periods
    assert period.description == description
    assert period.observation == observation
    assert period.planning_input == planning
    assert period.proposed == submitted
    assert period.decisions == submitted
    assert period.checks == [
        {
            "decisions": submitted,
            "outcomes": [
                {"decision_id": "1-1", "accepted": True},
                {"decision_id": "1-2", "accepted": True},
            ],
        }
    ]
    assert period.relaxed_program_value == pytest.approx(328)
    assert [solve.status for solve in period.solves] == [0, 0, 0]
    [relaxed, integer, fixed] = period.solves
    assert isinstance(relaxed, LinearSolve)
    assert isinstance(integer, IntegerSolve)
    assert isinstance(fixed, LinearSolve)
    assert relaxed.objective == pytest.approx(328)
    assert integer.value == pytest.approx(328)
    assert fixed.objective == pytest.approx(328)


def test_an_optimizer_retains_solver_and_check_inputs_when_the_check_fails():
    planning = plain_tiny_planning()

    def fail_check(
        _period: int, _decisions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        raise RuntimeError("check transport failed")

    optimizer = Optimizer(
        planning_source=lambda description, observation: planning,
        check=fail_check,
    )

    with pytest.raises(RuntimeError, match="check transport failed"):
        optimizer({"run_id": "r-1"}, {"period": 1})

    [period] = optimizer.periods
    assert period.error_type == "RuntimeError"
    assert period.error_message == "check transport failed"
    assert period.planning_input == planning
    assert period.proposed
    assert period.checks[0]["decisions"] == period.proposed
    assert period.checks[0]["outcomes"] is None
    assert [
        solve.kind for solve in period.solves if isinstance(solve, LinearSolve)
    ] == ["linear_relaxed", "linear_fixed_binary"]


def test_the_first_period_of_the_plain_tiny_factory_keeps_both_productions():
    decided = decide_by_program(accept_all, 60.0, plain_tiny_planning())

    assert (len(decided.decisions), decided.dropped, decided.fitted) == (2, [], [])


# A board takes 0.02 of space less 2 chips of 0.01, 0; a monitor 0.15 less 2 boards
# of 0.02, 0.11; the board, which frees more space, comes first.
def test_the_productions_of_the_plain_tiny_factory_come_board_first():
    planning = plain_tiny_planning()

    produces = order_produces(solve_program(planning), planning)

    assert [produce.item for produce in produces] == ["board", "monitor"]


def test_the_productions_of_the_plain_tiny_factory_pay_no_changeover():
    planning = plain_tiny_planning()
    produces = list(solve_program(planning).produces)

    assert paid_changeovers(produces, planning) == 0


# The line is set for no item at the start, so board, monitor and board again each
# pay a changeover.
def test_board_monitor_board_on_a_line_with_changeovers_pays_3():
    made = [
        {"kind": "produce", "line": "line-1", "item": item_id}
        for item_id in ("board", "monitor", "board")
    ]

    assert played_changeovers(made, changeover_planning()) == {"line-1": 3}


# A line set for `tablet`, which has no changeover terms, makes `panel`, which pays a
# changeover, and `tablet`, and ends set for `panel`: both orders pay 1 changeover. The
# space order plays `panel` first and leaves the line set for `tablet`.
def test_a_tie_of_changeovers_ends_the_line_set_for_the_item_the_program_planned():
    planning = plain_tiny_planning()
    line = planning.lines["line-1"]
    shares = line.items["board"].good_shares
    panel = LineItem(
        time=Decimal("0.1"),
        cost=Decimal(0),
        lead_time=1,
        good_shares=shares,
        changeover_time=Decimal(1),
        changeover_cost=Decimal(50),
    )
    tablet = replace(panel, changeover_time=Decimal(0), changeover_cost=Decimal(0))
    items = {
        "panel": Item(
            space=Decimal("0.01"),
            storage_cost=Decimal(0),
            salvage_value=Decimal(0),
            recipes={"standard": {}},
        ),
        "tablet": Item(
            space=Decimal("0.05"),
            storage_cost=Decimal(0),
            salvage_value=Decimal(0),
            recipes={"standard": {}},
        ),
    }
    planning = replace(
        planning,
        items={**planning.items, **items},
        lines={"line-1": replace(line, items={"panel": panel, "tablet": tablet})},
        state=replace(planning.state, set_for={"line-1": "tablet"}),
    )
    produces = tuple(
        SolutionProduce(
            line="line-1", item=item, recipe="standard", overtime=False, quantity=10.0
        )
        for item in ("panel", "tablet")
    )
    solution = replace(solution_of(produces=produces), set_at_close={"line-1": "panel"})

    ordered = order_produces(solution, planning)

    assert [produce.item for produce in ordered] == ["tablet", "panel"]
    assert played_changeovers(decisions_json(solution, planning), planning) == {
        "line-1": 1
    }


# The plain tiny planning input of a full warehouse: capacity 1, 60 chips
# of 0.01 and 4 boards of 0.1 fill it, a monitor takes 0.02, and the line is set for
# boards, each item with a changeover cost of 0.1.
def full_warehouse_planning() -> PlanningInput:
    planning = plain_tiny_planning()
    line = planning.lines["line-1"]
    items = {
        item_id: replace(item, changeover_cost=Decimal("0.1"))
        for item_id, item in line.items.items()
    }
    spaces = {
        "chip": Decimal("0.01"),
        "board": Decimal("0.1"),
        "monitor": Decimal("0.02"),
    }
    return replace(
        planning,
        items={
            item_id: replace(item, space=spaces[item_id])
            for item_id, item in planning.items.items()
        },
        lines={"line-1": replace(line, items=items)},
        warehouses={"main": replace(planning.warehouses["main"], capacity=Decimal(1))},
        state=replace(
            planning.state,
            stock={"main": {"chip": Decimal(60), "board": Decimal(4)}},
            set_for={"line-1": "board"},
        ),
    )


def made(line_id: str, item_id: str, quantity: float) -> SolutionProduce:
    return SolutionProduce(
        line=line_id, item=item_id, recipe="standard", overtime=False, quantity=quantity
    )


# One monitor frees 0.02 - 2 * 0.1 = -0.18 and two boards add 2 * (0.1 - 2 * 0.01) =
# 0.16. Boards first pay 1 changeover but find the warehouse full; the monitor first
# pays 2 and fits: 1 - 0.18 = 0.82, then 0.98.
def test_a_monitor_that_frees_space_comes_before_the_boards_of_a_full_warehouse():
    planning = full_warehouse_planning()
    solution = replace(
        solution_of(
            produces=(made("line-1", "board", 2.0), made("line-1", "monitor", 1.0))
        ),
        set_at_close={"line-1": "monitor"},
    )

    ordered = order_produces(solution, planning)

    assert [produce.item for produce in ordered] == ["monitor", "board"]
    assert paid_changeovers(ordered, planning) == 2


def test_2_boards_before_the_monitor_overfill_the_full_warehouse():
    planning = full_warehouse_planning()
    boards, monitor = made("line-1", "board", 2.0), made("line-1", "monitor", 1.0)
    solution = solution_of(produces=(boards, monitor))
    space_left = space_left_for_produces(solution, planning)

    assert space_left == {"main": Decimal(0)}
    assert space_added(boards, planning) == Decimal("0.16")
    assert space_added(monitor, planning) == Decimal("-0.18")
    assert not is_within_space([boards, monitor], space_left, planning)
    assert is_within_space([monitor, boards], space_left, planning)


# Line 1, set for boards at the start and at the close, makes a board, which adds no
# space, and a monitor, which adds 0.11; line 2, without changeovers, makes 2
# monitors. The changeover order ends line 1 with its board and pays 2 changeovers,
# the order by space pays 1. The order within space pays 1 too: the monitors of line
# 2 pay none and are not the item line 1 is set for at the close, so they go first.
def test_a_changeover_order_that_pays_more_gives_way_to_the_order_within_space():
    planning = changeover_planning()
    planning = replace(
        planning,
        lines={**planning.lines, "line-2": plain_tiny_planning().lines["line-1"]},
        state=replace(planning.state, set_for={"line-1": "board"}),
    )
    produces = (
        made("line-1", "board", 1.0),
        made("line-1", "monitor", 1.0),
        made("line-2", "monitor", 2.0),
    )
    solution = replace(solution_of(produces=produces), set_at_close={"line-1": "board"})

    ordered = order_produces(solution, planning)

    assert paid_changeovers(changeover_order(solution, planning), planning) == 2
    assert [(produce.line, produce.item) for produce in ordered] == [
        ("line-2", "monitor"),
        ("line-1", "board"),
        ("line-1", "monitor"),
    ]
    assert paid_changeovers(ordered, planning) == 1


# Line 1, set for boards, and line 2, set for monitors, share the full warehouse. The
# changeover order puts the boards of line 1 first, which find no space; the monitor
# of line 2 first frees 0.18 for them, and neither line pays a changeover.
def test_a_line_that_frees_space_goes_first_without_a_changeover_more():
    planning = full_warehouse_planning()
    line = planning.lines["line-1"]
    planning = replace(
        planning,
        lines={"line-1": line, "line-2": line},
        state=replace(planning.state, set_for={"line-1": "board", "line-2": "monitor"}),
    )
    solution = replace(
        solution_of(
            produces=(made("line-1", "board", 2.0), made("line-2", "monitor", 1.0))
        ),
        set_at_close={"line-1": "board", "line-2": "monitor"},
    )

    ordered = order_produces(solution, planning)

    assert [produce.line for produce in ordered] == ["line-2", "line-1"]
    assert paid_changeovers(ordered, planning) == 0
    assert paid_changeovers(changeover_order(solution, planning), planning) == 0


# A period of two lines that share one warehouse and make three items, each of space
# `spaces` hundredths from `chips` chips of 0.01, so a production adds from -0.3 to 0.5
# of space a unit. Each line starts set for an item of `set_for` or none, pays a
# changeover of 0.5 hours and 0.1 to every item, and has the hours of its productions
# and of the changeovers of the changeover order. The warehouse holds the chips with
# `extra` more and `fillers` units of space 1, and has room for the space every
# production adds together, with `spare` hundredths to spare.
def ordering_period(
    spaces: dict[str, int],
    chips: dict[str, int],
    produces: tuple[SolutionProduce, ...],
    set_for: dict[str, str | None],
    set_at_close: dict[str, str],
    extra: int,
    fillers: int,
    spare: int,
) -> tuple[Solution, PlanningInput]:
    planning = plain_tiny_planning()
    zero, hundredth = Decimal(0), Decimal("0.01")
    items = {
        item_id: Item(
            space=spaces[item_id] * hundredth,
            storage_cost=zero,
            salvage_value=zero,
            recipes={"standard": {"chip": Decimal(chips[item_id])}},
        )
        for item_id in "abc"
    }
    items["chip"] = replace(planning.items["chip"], space=hundredth)
    items["filler"] = replace(planning.items["chip"], space=Decimal(1))
    line_item = LineItem(
        time=Decimal("0.1"),
        cost=zero,
        lead_time=1,
        good_shares=planning.lines["line-1"].items["board"].good_shares,
        changeover_time=Decimal("0.5"),
        changeover_cost=Decimal("0.1"),
    )
    line = replace(planning.lines["line-1"], items=dict.fromkeys("abc", line_item))
    needed = sum(
        (Decimal(int(produce.quantity) * chips[produce.item]) for produce in produces),
        zero,
    )
    stock = {"chip": needed + extra, "filler": Decimal(fillers)}
    held = stock["chip"] * hundredth + stock["filler"]
    added = sum(
        (
            int(produce.quantity) * (spaces[produce.item] - chips[produce.item])
            for produce in produces
        ),
        0,
    )
    capacity = held + max(added, 0) * hundredth + spare * hundredth
    solution = replace(solution_of(produces=produces), set_at_close=set_at_close)
    planning = replace(
        planning,
        items=items,
        lines={"line-1": line, "line-2": line},
        warehouses={
            "main": replace(
                planning.warehouses["main"],
                capacity=capacity,
                accepts=tuple(sorted(items)),
            )
        },
        state=replace(planning.state, stock={"main": stock}, set_for=set_for),
    )
    planned = planned_changeovers(solution, planning)
    hours = {
        line_id: Hours(
            regular=sum(
                (
                    Decimal("0.1") * int(made.quantity)
                    for made in produces
                    if made.line == line_id
                ),
                zero,
            )
            + Decimal("0.5") * planned.get(line_id, 0),
            repair=zero,
            overtime=zero,
        )
        for line_id in ("line-1", "line-2")
    }
    return solution, replace(planning, state=replace(planning.state, hours=hours))


@st.composite
def ordering_periods(draw: st.DrawFn) -> tuple[Solution, PlanningInput]:
    spaces = {
        item_id: draw(st.integers(min_value=0, max_value=50)) for item_id in "abc"
    }
    chips = {item_id: draw(st.integers(min_value=0, max_value=30)) for item_id in "abc"}
    produces = tuple(
        made(line_id, item_id, float(quantity))
        for line_id, item_id, quantity in draw(
            st.lists(
                st.tuples(
                    st.sampled_from(["line-1", "line-2"]),
                    st.sampled_from("abc"),
                    st.integers(min_value=1, max_value=3),
                ),
                min_size=1,
                max_size=5,
            )
        )
    )
    set_for = {
        line_id: draw(st.sampled_from([None, "a", "b", "c"]))
        for line_id in ("line-1", "line-2")
    }
    set_at_close = {
        line_id: draw(
            st.sampled_from([made.item for made in produces if made.line == line_id])
        )
        for line_id in ("line-1", "line-2")
        if any(made.line == line_id for made in produces)
    }
    return ordering_period(
        spaces,
        chips,
        produces,
        set_for,
        set_at_close,
        draw(st.integers(min_value=0, max_value=10)),
        draw(st.integers(min_value=0, max_value=3)),
        draw(st.integers(min_value=0, max_value=30)),
    )


# Every order of productions runs as the engine checks it: from the space held at the
# start, each production adds its units times its space less its chips times 0.01, and
# the warehouse never holds more than its capacity; the chips taken never exceed the
# stock; on every line the production hours and the changeovers paid fit its hours, or
# the order pays more changeovers than the program counts, and the report says so.
# The order pays no more changeovers than the order by space, which puts first the
# productions that free the most space a unit; where the changeover order fits, it
# pays no more than that order either. In the example, line 1, set for none, makes one
# b, which frees 0.01, and two units of a, which add 0.01 each, into a warehouse with
# 0.01 free. The order within space makes a, then b to free the space, then a again: 3
# changeovers. The order by space, b first, pays 2, so it is the order.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(ordering_periods())
@example(
    period=ordering_period(
        {"a": 1, "b": 0, "c": 0},
        {"a": 0, "b": 1, "c": 0},
        (made("line-1", "b", 1.0), made("line-1", "a", 1.0), made("line-1", "a", 1.0)),
        {"line-1": None, "line-2": None},
        {"line-1": "b"},
        0,
        0,
        0,
    )
)
def test_every_order_of_productions_fits_its_warehouse_its_inputs_and_its_hours(
    period: tuple[Solution, PlanningInput],
):
    solution, planning = period
    stock = planning.state.stock["main"]

    ordered = order_produces(solution, planning)

    assert sorted(ordered, key=repr) == sorted(solution.produces, key=repr)
    held = stock["chip"] * Decimal("0.01") + stock["filler"]
    chips = stock["chip"]
    for produce in ordered:
        taken = (
            int(produce.quantity)
            * planning.items[produce.item].recipes["standard"]["chip"]
        )
        held += int(produce.quantity) * planning.items[
            produce.item
        ].space - taken * Decimal("0.01")
        chips -= taken
        assert held <= planning.warehouses["main"].capacity
        assert chips >= 0
    decisions = [produce_decision(produce) for produce in ordered]
    paid = played_changeovers(decisions, planning)
    planned = planned_changeovers(solution, planning)
    for line_id, hours in planning.state.hours.items():
        used = (
            sum(
                (
                    Decimal("0.1") * int(made.quantity)
                    for made in ordered
                    if made.line == line_id
                ),
                Decimal(0),
            )
            + Decimal("0.5") * paid[line_id]
        )
        assert used <= hours.regular or paid[line_id] > planned[line_id]
    by_space = sorted(
        solution.produces,
        key=lambda produce: (
            planning.items[produce.item].space
            - planning.items[produce.item].recipes["standard"]["chip"] * Decimal("0.01")
        ),
    )
    assert paid_changeovers(ordered, planning) <= paid_changeovers(by_space, planning)
    by_changeover = changeover_order(solution, planning)
    space_left = space_left_for_produces(solution, planning)
    if is_within_space(by_changeover, space_left, planning):
        assert paid_changeovers(ordered, planning) <= paid_changeovers(
            by_changeover, planning
        )


def test_a_monitor_adds_its_space_less_the_space_of_its_2_boards():
    space = space_change("monitor", "standard", plain_tiny_planning())

    assert space == Decimal("0.11")


def test_a_buy_of_chips_adds_the_space_of_a_chip():
    space = unit_space({"kind": "buy", "material": "chip"}, plain_tiny_planning())

    assert space == Decimal("0.01")


# 0.004 of space missing over 0.01 per chip leaves 10 - 0.4 = 9.6 chips.
def test_a_transfer_short_of_space_gives_up_the_units_of_the_missing_space():
    transfer = {"kind": "transfer", "item": "chip", "quantity": Decimal("10.000")}
    outcome = {
        "decision_id": "2-1",
        "accepted": False,
        "reason": "not_enough_space",
        "asked": Decimal("5.004"),
        "available": Decimal("5.000"),
    }

    changes = fitted_quantities([transfer], [outcome], plain_tiny_planning())

    assert changes == {0: ("not_enough_space", Decimal("9.600"))}


# 0.2 of space missing over 0.01 per chip is 20 chips, more than the 10 sent, so the
# transfer is left out and its fit records 0.
def test_a_transfer_short_of_more_space_than_it_adds_is_fitted_to_0():
    transfer = {"kind": "transfer", "item": "chip", "quantity": Decimal("10.000")}
    short = {
        "decision_id": "1-1",
        "accepted": False,
        "reason": "not_enough_space",
        "asked": Decimal("5.200"),
        "available": Decimal("5.000"),
    }
    answers = [[short], []]

    def check(_period: int, _decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return answers.pop(0)

    accepted, _, fitted = check_and_fit(check, [transfer], plain_tiny_planning())

    assert accepted == []
    assert [entry["after"] for entry in fitted] == [Decimal(0)]


# A unit of `component-1` of space 5.610 takes 1.168 units of `material-1` of space
# 3.153, so it adds 5.610 - 1.168 * 3.153 = 1.927296; the engine rounds the inputs up.
# 1.245 units take 1.455 and add 2.396835, 0.016337 more than the 2.380498 free; the
# fit takes 0.016337 / 1.927296 = 0.008477 units, to 1.236. 1.236 units take 1.444 and
# add 2.381028, 0.00053 more; the fit takes 0.00053 / 1.927296 = 0.000275 units, to
# 1.235, which takes 1.443 and adds 2.378571.
def test_a_production_whose_rounded_inputs_free_less_space_is_fitted_until_it_fits():
    material = Item(
        space=Decimal("3.153"),
        storage_cost=Decimal(0),
        salvage_value=Decimal(0),
        recipes={},
    )
    component = Item(
        space=Decimal("5.610"),
        storage_cost=Decimal(0),
        salvage_value=Decimal(0),
        recipes={"alternative": {"material-1": Decimal("1.168")}},
    )
    planning = replace(
        plain_tiny_planning(),
        items={"material-1": material, "component-1": component},
    )
    produce = {
        "kind": "produce",
        "line": "line-1",
        "item": "component-1",
        "quantity": Decimal("1.245"),
        "recipe": "alternative",
        "overtime": False,
    }
    available = Decimal("2.380498")

    def check(period: int, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        quantity = decisions[0]["quantity"]
        taken = (quantity * Decimal("1.168")).quantize(QUANTITY_EXPONENT, ROUND_CEILING)
        asked = quantity * Decimal("5.610") - taken * Decimal("3.153")
        if asked <= available:
            return [{"decision_id": f"{period}-1", "accepted": True}]
        short = {"accepted": False, "reason": "not_enough_space"}
        return [
            short
            | {"decision_id": f"{period}-1", "asked": asked, "available": available}
        ]

    accepted, dropped, fitted = check_and_fit(check, [produce], planning)

    assert accepted == [produce | {"quantity": Decimal("1.235")}]
    assert dropped == []
    assert [(entry["before"], entry["after"]) for entry in fitted] == [
        (Decimal("1.245"), Decimal("1.236")),
        (Decimal("1.236"), Decimal("1.235")),
    ]


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(st.floats(min_value=0, max_value=10**6))
def test_a_rounded_value_is_within_a_thousandth_below_the_value(value: float):
    rounded = round_down(value, QUANTITY_EXPONENT)

    assert rounded <= Decimal(value) + Decimal("1e-9")
    assert rounded > Decimal(value) - Decimal("0.001")
    assert rounded.as_tuple().exponent == -3
