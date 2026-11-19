"""The decisions of a solution: rounded down, ordered, checked and fitted.

Examples:
    >>> round_down(2.0004, QUANTITY_EXPONENT)
    Decimal('2.000')
"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import cast

from factory_simulator.benchmark.client import Check, JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.models.outputs import (
    IntegerSolve,
    LinearSolve,
    Solution,
    SolutionProduce,
)
from factory_simulator.benchmark.program.solve import (
    TIME_LIMIT,
    changeover_lines,
    solve_program,
    solve_relaxed,
)

TOLERANCE = Decimal("1e-9")
QUANTITY_EXPONENT = Decimal("0.001")
AMOUNT_EXPONENT = Decimal("0.0001")

type PlanningSource = Callable[[JsonObject, JsonObject], PlanningInput]
"""A planning source: a function of the description of a run and the observation of a
period that gives the planning input of the period."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DecidedPeriod:
    """The decisions of a period an optimizer submits, with what it learned on the way.

    Attributes:
        decisions (list[dict[str, Any]]): The decisions the last check accepts.
        proposed (list[dict[str, Any]]): The initial plan before checking or fitting.
        checks (list[dict[str, Any]]): Every checked plan and its outcomes.
        integer_solve (IntegerSolve | None): The report of the solve of an integer
            program; None for a linear one.
        linear_solve (LinearSolve | None): The report of the solve of a linear
            program; None for an integer one.
        dropped (list[dict[str, Any]]): Every decision the last check rejects, with its
            period and reason.
        fitted (list[dict[str, Any]]): Every decision the fit changed, with its period,
            reason and quantity before and after.

    Examples:
        >>> DecidedPeriod(
        ...     decisions=[],
        ...     proposed=[],
        ...     checks=[],
        ...     integer_solve=None,
        ...     linear_solve=None,
        ...     dropped=[],
        ...     fitted=[],
        ... ).decisions
        []
    """

    decisions: list[JsonObject]
    proposed: list[JsonObject]
    checks: list[JsonObject]
    integer_solve: IntegerSolve | None
    linear_solve: LinearSolve | None
    dropped: list[JsonObject]
    fitted: list[JsonObject]


@dataclass(frozen=True, slots=True, kw_only=True)
class OptimizerPeriod:
    """The planning input and the decisions of one period of an optimizer.

    Attributes:
        period (int): The period.
        description (dict[str, Any]): The description of the run.
        observation (dict[str, Any]): The observation of the period.
        planning_input (PlanningInput | None): The planning input of the period; None
            when the planning source raises an error.
        proposed (list[dict[str, Any]]): The initial plan before checking or fitting.
        checks (list[dict[str, Any]]): Every checked plan and its outcomes.
        decisions (list[dict[str, Any]]): The decisions the optimizer submits.
        dropped (list[dict[str, Any]]): Every decision the last check rejects, with its
            period and reason.
        fitted (list[dict[str, Any]]): Every decision the fit changed, with its period,
            reason and quantity before and after.
        integer_solve (IntegerSolve | None): The report of the solve of an integer
            program; None for a linear one.
        solves (list[IntegerSolve | LinearSolve]): The report of every solve of the
            period.
        relaxed_program_value (float | None): The value of `solve_relaxed` in the first
            period; None in every other period.
        error_type (str | None, optional): The name of the class of the error the
            period raises; None without one.
        error_message (str | None, optional): The message of the error the period
            raises; None without one.

    Examples:
        >>> period = OptimizerPeriod(
        ...     period=1,
        ...     description={},
        ...     observation={},
        ...     planning_input=None,
        ...     proposed=[],
        ...     checks=[],
        ...     decisions=[],
        ...     dropped=[],
        ...     fitted=[],
        ...     integer_solve=None,
        ...     solves=[],
        ...     relaxed_program_value=None,
        ... )
        >>> period.period
        1
    """

    period: int
    description: JsonObject
    observation: JsonObject
    planning_input: PlanningInput | None
    proposed: list[JsonObject]
    checks: list[JsonObject]
    decisions: list[JsonObject]
    dropped: list[JsonObject]
    fitted: list[JsonObject]
    integer_solve: IntegerSolve | None
    solves: list[IntegerSolve | LinearSolve]
    relaxed_program_value: float | None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(slots=True, kw_only=True)
class Optimizer:
    """An agent that solves a program of profit over coming periods from what it knows.

    Attributes:
        planning_source (Callable[[dict[str, Any], dict[str, Any]], PlanningInput]): The
            function that gives the planning input of a period.
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period of its run.
        time_limit (float, optional): Seconds every solve of a period may take.
        relaxed_time_limit (float | None, optional): Seconds the relaxed program may
            take; None for no limit.
        solves (list[IntegerSolve], optional): The report of every integer program
            solved.
        dropped (list[dict[str, Any]], optional): Every decision the last check of its
            period refuses, with its period and reason.
        fitted (list[dict[str, Any]], optional): Every decision the fit changed, with
            its period, reason and quantity before and after.
        periods (list[OptimizerPeriod], optional): The planning and decision trace of
            every callback.
        relaxed_program_value (float | None, optional): The value of `solve_relaxed`
            in its first period; None before it.
        exact (bool, optional): Whether every choice of its program is binary in
            every period of the window, for a small world only.
        purchase_budget_cap (Decimal | None, optional): The most the buys of each
            period of the window may cost; None for no limit.

    Examples:
        >>> from factory_simulator.benchmark.program.expected_source import (
        ...     LEAN_TERMINAL_VALUE_FACTOR,
        ...     expected_planning_source,
        ... )
        >>> optimizer = Optimizer(
        ...     planning_source=expected_planning_source(
        ...         "horizon", "expected", LEAN_TERMINAL_VALUE_FACTOR
        ...     ),
        ...     check=lambda period, decisions: [],
        ... )
        >>> optimizer.relaxed_program_value is None
        True
    """

    planning_source: PlanningSource
    check: Check
    time_limit: float = TIME_LIMIT
    relaxed_time_limit: float | None = None
    solves: list[IntegerSolve] = field(default_factory=list[IntegerSolve])
    dropped: list[JsonObject] = field(default_factory=list[JsonObject])
    fitted: list[JsonObject] = field(default_factory=list[JsonObject])
    periods: list[OptimizerPeriod] = field(default_factory=list[OptimizerPeriod])
    relaxed_program_value: float | None = None
    exact: bool = False
    purchase_budget_cap: Decimal | None = None

    def __call__(
        self, description: JsonObject, observation: JsonObject
    ) -> list[JsonObject]:
        """Decide a period by the program and keep what the period teaches.

        In its first period it also keeps the value of the relaxed program.

        Args:
            description (dict[str, Any]): The description of the run.
            observation (dict[str, Any]): The observation of the period.

        Returns:
            list[dict[str, Any]]: The decisions of the period of `decide_by_program`.

        Examples:
            >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
            >>> state = WindowStart(
            ...     cash=Decimal(1000),
            ...     stock={},
            ...     conditions={},
            ...     hours={},
            ...     production=(),
            ...     transfers=(),
            ...     supplier_orders=(),
            ...     receivables=(),
            ... )
            >>> cash = Cash(
            ...     credit_limit=Decimal(0),
            ...     credit_interest=Decimal(0),
            ...     debit_interest=Decimal(0),
            ...     overdraft_interest=Decimal(0),
            ... )
            >>> planning = PlanningInput(
            ...     first_period=1,
            ...     window_end=1,
            ...     horizon=1,
            ...     starting_cash=Decimal(1000),
            ...     items={},
            ...     lines={},
            ...     warehouses={},
            ...     routes=(),
            ...     customers={},
            ...     cash=cash,
            ...     state=state,
            ...     customer_orders=(),
            ...     buy_options=(),
            ... )
            >>> optimizer = Optimizer(
            ...     planning_source=lambda description, observation: planning,
            ...     check=lambda period, decisions: [],
            ... )
            >>> optimizer({}, {}), optimizer.relaxed_program_value
            ([], 0.0)
        """
        try:
            planning = self.planning_source(description, observation)
            if self.purchase_budget_cap is not None:
                planning = replace(
                    planning, purchase_budget_cap=self.purchase_budget_cap
                )
        except BaseException as error:
            self.periods.append(
                OptimizerPeriod(
                    period=int(observation.get("period", 0)),
                    description=deepcopy(description),
                    observation=deepcopy(observation),
                    planning_input=None,
                    proposed=[],
                    checks=[],
                    decisions=[],
                    dropped=[],
                    fitted=[],
                    integer_solve=None,
                    solves=[],
                    relaxed_program_value=None,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
            )
            raise
        relaxed_value = None
        if self.relaxed_program_value is None:
            relaxed_solves: list[LinearSolve] = []
            try:
                self.relaxed_program_value = solve_relaxed(
                    planning, relaxed_solves, self.relaxed_time_limit
                )
            except BaseException as error:
                self.periods.append(
                    OptimizerPeriod(
                        period=planning.first_period,
                        description=deepcopy(description),
                        observation=deepcopy(observation),
                        planning_input=planning,
                        proposed=[],
                        checks=[],
                        decisions=[],
                        dropped=[],
                        fitted=[],
                        integer_solve=None,
                        solves=cast(list[IntegerSolve | LinearSolve], relaxed_solves),
                        relaxed_program_value=None,
                        error_type=type(error).__name__,
                        error_message=str(error),
                    )
                )
                raise
            relaxed_value = self.relaxed_program_value
        else:
            relaxed_solves = []
        trace: dict[str, object] = {}
        try:
            decided = decide_by_program(
                self.check,
                self.time_limit,
                planning,
                self.exact,
                trace=trace,
            )
        except BaseException as error:
            self.periods.append(
                OptimizerPeriod(
                    period=planning.first_period,
                    description=deepcopy(description),
                    observation=deepcopy(observation),
                    planning_input=planning,
                    proposed=cast(list[JsonObject], trace.get("proposed", [])),
                    checks=cast(list[JsonObject], trace.get("checks", [])),
                    decisions=cast(list[JsonObject], trace.get("decisions", [])),
                    dropped=cast(list[JsonObject], trace.get("dropped", [])),
                    fitted=cast(list[JsonObject], trace.get("fitted", [])),
                    integer_solve=cast(IntegerSolve | None, trace.get("integer_solve")),
                    solves=[
                        *relaxed_solves,
                        *cast(
                            list[IntegerSolve | LinearSolve],
                            trace.get("solves", []),
                        ),
                    ],
                    relaxed_program_value=relaxed_value,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
            )
            raise
        if decided.integer_solve is not None:
            self.solves.append(decided.integer_solve)
        self.dropped.extend(decided.dropped)
        self.fitted.extend(decided.fitted)
        solver_reports: list[IntegerSolve | LinearSolve] = [
            *relaxed_solves,
            *cast(list[IntegerSolve | LinearSolve], trace.get("solves", [])),
        ]
        self.periods.append(
            OptimizerPeriod(
                period=planning.first_period,
                description=deepcopy(description),
                observation=deepcopy(observation),
                planning_input=planning,
                proposed=deepcopy(decided.proposed),
                checks=deepcopy(decided.checks),
                decisions=deepcopy(decided.decisions),
                dropped=deepcopy(decided.dropped),
                fitted=deepcopy(decided.fitted),
                integer_solve=decided.integer_solve,
                solves=solver_reports,
                relaxed_program_value=relaxed_value,
            )
        )
        return decided.decisions


def decide_by_program(
    check: Check,
    time_limit: float,
    planning: PlanningInput,
    exact: bool = False,
    *,
    trace: dict[str, object] | None = None,
) -> DecidedPeriod:
    """Decide a period: solve the program, round its decisions, check and fit them.

    The report of an integer solve counts the changeovers the rounded decisions pay
    and those of the changeover order, which the program counts. A period without a
    decision calls no check.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period.
        time_limit (float): Seconds the solve of an integer program may take.
        planning (PlanningInput): The planning input of the period.
        exact (bool, optional): Whether every choice of the program is binary in
            every period of the window.
        trace (dict[str, object] | None, optional): Captures the plan, solves and
            check inputs as they become available, changed in place.

    Returns:
        DecidedPeriod: The plan, checks, accepted decisions and solve report.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> decided = decide_by_program(lambda period, decisions: [], 60.0, planning)
        >>> decided.decisions, decided.dropped, decided.fitted
        ([], [], [])
    """
    solve_reports: list[IntegerSolve | LinearSolve] = []
    try:
        solution = solve_program(
            planning,
            time_limit,
            exact,
            diagnostics=solve_reports if trace is not None else None,
        )
    except BaseException:
        if trace is not None:
            trace["solves"] = solve_reports
        raise
    decisions = decisions_json(solution, planning)
    proposed = deepcopy(decisions)
    if trace is not None:
        solves: list[IntegerSolve | LinearSolve] = []
        if solution.integer_solve is not None:
            solves.append(solution.integer_solve)
            if solution.integer_solve.fixed_binary_solve is not None:
                solves.append(solution.integer_solve.fixed_binary_solve)
        elif solution.linear_solve is not None:
            solves.append(solution.linear_solve)
        trace.update(
            proposed=deepcopy(proposed),
            decisions=[],
            integer_solve=solution.integer_solve,
            solves=solve_reports or solves,
        )
    integer_solve = solution.integer_solve
    if integer_solve is not None:
        integer_solve = replace(
            integer_solve,
            changeovers=played_changeovers(decisions, planning),
            planned_changeovers=planned_changeovers(solution, planning),
        )
    if not decisions:
        return DecidedPeriod(
            decisions=[],
            proposed=proposed,
            checks=[],
            integer_solve=integer_solve,
            linear_solve=solution.linear_solve,
            dropped=[],
            fitted=[],
        )
    checks: list[JsonObject] = []
    if trace is not None:
        trace["checks"] = checks
    accepted, dropped, fitted = check_and_fit(check, decisions, planning, checks)
    if trace is not None:
        trace.update(decisions=accepted, dropped=dropped, fitted=fitted)
    return DecidedPeriod(
        decisions=accepted,
        proposed=proposed,
        checks=checks,
        integer_solve=integer_solve,
        linear_solve=solution.linear_solve,
        dropped=dropped,
        fitted=fitted,
    )


def round_down(value: float | Decimal, exponent: Decimal) -> Decimal:
    """Round a value down to an exponent after a tolerance of 1e-9.

    Args:
        value (float | Decimal): A value of a solution or of an answer.
        exponent (Decimal): The exponent to keep, such as `QUANTITY_EXPONENT`.

    Returns:
        Decimal: The value plus 1e-9, rounded down to `exponent`.

    Examples:
        >>> round_down(39.9999999996, QUANTITY_EXPONENT)
        Decimal('40.000')
        >>> round_down(0.12345678, AMOUNT_EXPONENT)
        Decimal('0.1234')
    """
    return (Decimal(value) + TOLERANCE).quantize(exponent, rounding=ROUND_FLOOR)


def decisions_json(solution: Solution, planning: PlanningInput) -> list[JsonObject]:
    """Write the decisions of the first period of a solution, rounded down.

    Quantities keep 3 places and repair amounts 4; a value that rounds to 0 gives no
    decision. The productions come in the order of `order_produces`.

    Args:
        solution (Solution): The solution.
        planning (PlanningInput): The planning input.

    Returns:
        list[dict[str, Any]]: The decisions in the order ship, transfer, repair,
            produce, buy, with every key written.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> from factory_simulator.benchmark.models.outputs import SolutionRepair
        >>> repair = SolutionRepair(line="line-1", amount=0.25000001)
        >>> solution = Solution(
        ...     value=0.0,
        ...     ships=(),
        ...     transfers=(),
        ...     repairs=(repair,),
        ...     produces=(),
        ...     buys=(),
        ... )
        >>> decisions_json(solution, planning)
        [{'kind': 'repair', 'line': 'line-1', 'amount': Decimal('0.2500')}]
    """
    decisions: list[JsonObject] = []
    for ship in solution.ships:
        decisions.append(
            {
                "kind": "ship",
                "order": ship.order,
                "quantity": round_down(ship.quantity, QUANTITY_EXPONENT),
                "warehouse": ship.warehouse,
            }
        )
    for transfer in solution.transfers:
        decisions.append(
            {
                "kind": "transfer",
                "item": transfer.item,
                "quantity": round_down(transfer.quantity, QUANTITY_EXPONENT),
                "source": transfer.source,
                "destination": transfer.destination,
            }
        )
    for repair in solution.repairs:
        decisions.append(
            {
                "kind": "repair",
                "line": repair.line,
                "amount": round_down(repair.amount, AMOUNT_EXPONENT),
            }
        )
    decisions.extend(
        produce_decision(produce) for produce in order_produces(solution, planning)
    )
    for buy in solution.buys:
        decisions.append(
            {
                "kind": "buy",
                "supplier": buy.supplier,
                "material": buy.material,
                "quantity": round_down(buy.quantity, QUANTITY_EXPONENT),
                "warehouse": buy.warehouse,
                "express": buy.express,
            }
        )
    return [decision for decision in decisions if is_above_zero(decision)]


def produce_decision(produce: SolutionProduce) -> JsonObject:
    """Give the produce decision of a production, its quantity rounded down.

    Args:
        produce (SolutionProduce): The production.

    Returns:
        dict[str, Any]: The decision with every key written.

    Examples:
        >>> produce = SolutionProduce(
        ...     line="line-1",
        ...     item="board",
        ...     recipe="standard",
        ...     overtime=False,
        ...     quantity=7.9999999999,
        ... )
        >>> produce_decision(produce)["quantity"]
        Decimal('8.000')
    """
    return {
        "kind": "produce",
        "line": produce.line,
        "item": produce.item,
        "quantity": round_down(produce.quantity, QUANTITY_EXPONENT),
        "recipe": produce.recipe,
        "overtime": produce.overtime,
    }


def is_above_zero(decision: JsonObject) -> bool:
    """Tell whether the quantity or amount of a decision is above 0.

    Args:
        decision (dict[str, Any]): The decision.

    Returns:
        bool: True when its `amount`, or else its `quantity`, is above 0.

    Examples:
        >>> is_above_zero({"kind": "repair", "amount": Decimal("0.0000")})
        False
    """
    if "amount" in decision:
        return decision["amount"] > 0
    return decision["quantity"] > 0


def order_produces(
    solution: Solution, planning: PlanningInput
) -> list[SolutionProduce]:
    """Order the productions of a solution as they are decided.

    The order by space puts the productions that free space in their warehouse first,
    so that no check of space sees more than the space rows allow. The changeover
    order of `changeover_order` takes its place when it pays no more changeovers and
    every production of it fits the space left in its warehouse. When the changeover
    order pays more or does not fit, `order_within_space` gives an order in which
    every production fits; it takes the place of the order by space when it pays no
    more changeovers.

    Args:
        solution (Solution): The solution.
        planning (PlanningInput): The planning input.

    Returns:
        list[SolutionProduce]: The productions in their order.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> order_produces(solve_program(planning), planning)
        []
    """
    by_space = sorted(
        solution.produces,
        key=lambda produce: space_change(produce.item, produce.recipe, planning),
    )
    by_changeover = changeover_order(solution, planning)
    space_left = space_left_for_produces(solution, planning)
    paid_by_space = paid_changeovers(by_space, planning)
    pays_no_more = paid_changeovers(by_changeover, planning) <= paid_by_space
    if pays_no_more and is_within_space(by_changeover, space_left, planning):
        return by_changeover
    within = order_within_space(by_space, space_left, solution, planning)
    if paid_changeovers(within, planning) <= paid_by_space:
        return within
    return by_space


def changeover_order(
    solution: Solution, planning: PlanningInput
) -> list[SolutionProduce]:
    """Give the productions of a solution in the changeover order.

    On a changeover line the item the line is set for comes first and the item it is
    set for at the close last, the productions of one item together, so the order
    pays the changeovers the program counts. The productions of one place come in the
    order by space.

    Args:
        solution (Solution): The solution.
        planning (PlanningInput): The planning input.

    Returns:
        list[SolutionProduce]: The productions in the changeover order.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> changeover_order(solve_program(planning), planning)
        []
    """
    by_space = sorted(
        solution.produces,
        key=lambda produce: space_change(produce.item, produce.recipe, planning),
    )
    lines = changeover_lines(planning)

    def place(produce: SolutionProduce) -> tuple[int, str]:
        if produce.line not in lines:
            return 1, ""
        if solution.set_at_close.get(produce.line) == produce.item:
            return 2, produce.item
        if planning.state.set_for.get(produce.line) == produce.item:
            return 0, produce.item
        return 1, produce.item

    return sorted(by_space, key=place)


def space_left_for_produces(
    solution: Solution, planning: PlanningInput
) -> dict[str, Decimal]:
    """Give the space left in each warehouse when the productions of a solution start.

    The space held is the space the engine checks: stock, production not yet in stock,
    open supplier orders and transfers on the way, less the rounded shipments, and with
    the rounded transfers of the period out of their source and into their destination.

    Args:
        solution (Solution): The solution.
        planning (PlanningInput): The planning input.

    Returns:
        dict[str, Decimal]: The capacity less the space held, by warehouse.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> space_left_for_produces(solve_program(planning), planning)
        {}
    """
    space = {item_id: item.space for item_id, item in planning.items.items()}
    state = planning.state
    held = dict.fromkeys(planning.warehouses, Decimal(0))
    for warehouse_id, stock in state.stock.items():
        for item_id, units in stock.items():
            held[warehouse_id] += units * space[item_id]
    for production in state.production:
        held[production.warehouse] += production.started * space[production.item]
    for order in state.supplier_orders:
        held[order.warehouse] += order.open_quantity * space[order.material]
    for transfer in state.transfers:
        held[transfer.destination] += transfer.quantity * space[transfer.item]
    products = {order.id: order.product for order in planning.customer_orders}
    for ship in solution.ships:
        shipped = round_down(ship.quantity, QUANTITY_EXPONENT)
        held[ship.warehouse] -= shipped * space[products[ship.order]]
    for transfer in solution.transfers:
        moved = round_down(transfer.quantity, QUANTITY_EXPONENT) * space[transfer.item]
        held[transfer.source] -= moved
        held[transfer.destination] += moved
    return {
        warehouse_id: warehouse.capacity - held[warehouse_id]
        for warehouse_id, warehouse in planning.warehouses.items()
    }


def space_added(produce: SolutionProduce, planning: PlanningInput) -> Decimal:
    """Give the space a production adds in its warehouse, as the engine checks it.

    Args:
        produce (SolutionProduce): The production.
        planning (PlanningInput): The planning input.

    Returns:
        Decimal: The space of its rounded quantity less the space of its inputs, each
            rounded up to 3 places.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     Cash,
        ...     Item,
        ...     WindowStart,
        ... )
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> chip = Item(
        ...     space=Decimal("0.01"),
        ...     storage_cost=Decimal(0),
        ...     salvage_value=Decimal(0),
        ...     recipes={},
        ... )
        >>> board = Item(
        ...     space=Decimal("0.1"),
        ...     storage_cost=Decimal(0),
        ...     salvage_value=Decimal(0),
        ...     recipes={"standard": {"chip": Decimal(2)}},
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     lines={},
        ...     warehouses={},
        ...     items={"chip": chip, "board": board},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> produce = SolutionProduce(
        ...     line="line-1",
        ...     item="board",
        ...     recipe="standard",
        ...     overtime=False,
        ...     quantity=2.0,
        ... )
        >>> space_added(produce, planning)
        Decimal('0.16000')
    """
    quantity = round_down(produce.quantity, QUANTITY_EXPONENT)
    item = planning.items[produce.item]
    inputs = sum(
        (
            (quantity * per_unit).quantize(QUANTITY_EXPONENT, rounding=ROUND_CEILING)
            * planning.items[input_id].space
            for input_id, per_unit in sorted(item.recipes[produce.recipe].items())
        ),
        Decimal(0),
    )
    return quantity * item.space - inputs


def is_within_space(
    produces: list[SolutionProduce],
    space_left: Mapping[str, Decimal],
    planning: PlanningInput,
) -> bool:
    """Tell whether every production fits the space left in its warehouse, in order.

    Args:
        produces (list[SolutionProduce]): The productions, in their order.
        space_left (Mapping[str, Decimal]): The space left in each warehouse before
            the first production.
        planning (PlanningInput): The planning input.

    Returns:
        bool: True when no production adds more space than its warehouse has left
            after the productions before it.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> is_within_space([], {}, planning)
        True
    """
    left = dict(space_left)
    for produce in produces:
        warehouse_id = planning.lines[produce.line].warehouse
        added = space_added(produce, planning)
        if added > left[warehouse_id]:
            return False
        left[warehouse_id] -= added
    return True


def order_within_space(
    produces: list[SolutionProduce],
    space_left: Mapping[str, Decimal],
    solution: Solution,
    planning: PlanningInput,
) -> list[SolutionProduce]:
    """Order the productions so that each fits the space left before it.

    Each next production is one that fits, when one does, that pays the fewest
    changeovers now and later: none when its line is set for its item, one when the
    line switches from an item it has no production of left, two when it does. A tie
    goes to an item other than the one the line is set for at the close, then to the
    production that adds the least space.

    Args:
        produces (list[SolutionProduce]): The productions.
        space_left (Mapping[str, Decimal]): The space left in each warehouse before
            the first production.
        solution (Solution): The solution, with the item each changeover line is set
            for at the close.
        planning (PlanningInput): The planning input.

    Returns:
        list[SolutionProduce]: The productions in their order.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> order_within_space([], {}, solve_program(planning), planning)
        []
    """
    lines = changeover_lines(planning)
    setting = dict(planning.state.set_for)
    left = dict(space_left)
    remaining = list(produces)
    ordered: list[SolutionProduce] = []

    def rank(produce: SolutionProduce) -> tuple[bool, int, bool, Decimal]:
        added = space_added(produce, planning)
        fits = added <= left[planning.lines[produce.line].warehouse]
        current = setting.get(produce.line)
        item = planning.lines[produce.line].items[produce.item]
        has_changeover = item.changeover_time > 0 or item.changeover_cost > 0
        changeovers = 0
        if produce.line in lines and has_changeover and current != produce.item:
            changeovers = 1
            # Leaving an item with productions left pays a changeover back to it.
            if any(
                other.line == produce.line and other.item == current
                for other in remaining
            ):
                changeovers = 2
        closes = solution.set_at_close.get(produce.line) == produce.item
        return not fits, changeovers, closes, added

    while remaining:
        chosen = min(remaining, key=rank)
        remaining.remove(chosen)
        ordered.append(chosen)
        if round_down(chosen.quantity, QUANTITY_EXPONENT) > 0:
            left[planning.lines[chosen.line].warehouse] -= space_added(chosen, planning)
            setting[chosen.line] = chosen.item
    return ordered


def planned_changeovers(solution: Solution, planning: PlanningInput) -> dict[str, int]:
    """Give the changeovers the program counts for the productions of a solution.

    Args:
        solution (Solution): The solution.
        planning (PlanningInput): The planning input.

    Returns:
        dict[str, int]: The changeovers of every changeover line that the rounded
            decisions pay in the changeover order.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> planned_changeovers(solve_program(planning), planning)
        {}
    """
    decisions = [
        produce_decision(produce) for produce in changeover_order(solution, planning)
    ]
    return played_changeovers(
        [decision for decision in decisions if is_above_zero(decision)], planning
    )


def paid_changeovers(produces: list[SolutionProduce], planning: PlanningInput) -> int:
    """Give the changeovers the rounded decisions of productions pay, in their order.

    Args:
        produces (list[SolutionProduce]): The productions, in their order.
        planning (PlanningInput): The planning input.

    Returns:
        int: The changeovers of every changeover line together.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> paid_changeovers([], planning)
        0
    """
    decisions = [produce_decision(produce) for produce in produces]
    played = played_changeovers(
        [decision for decision in decisions if is_above_zero(decision)], planning
    )
    return sum(played.values())


def played_changeovers(
    decisions: list[JsonObject], planning: PlanningInput
) -> dict[str, int]:
    """Give the changeovers the engine pays for rounded decisions.

    The produce decisions run in their order; one of an item with a changeover time
    or cost pays a changeover when the line is set for another item or for none, and
    every produce decision sets the line for its item.

    Args:
        decisions (list[dict[str, Any]]): The decisions, in their order.
        planning (PlanningInput): The planning input.

    Returns:
        dict[str, int]: The changeovers of every changeover line.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> played_changeovers([{"kind": "repair", "line": "line-1"}], planning)
        {}
    """
    changeovers: dict[str, int] = {}
    for line_id in changeover_lines(planning):
        items = planning.lines[line_id].items
        setting = planning.state.set_for.get(line_id)
        count = 0
        for decision in decisions:
            if decision["kind"] != "produce" or decision["line"] != line_id:
                continue
            item = items[decision["item"]]
            has_changeover = item.changeover_time > 0 or item.changeover_cost > 0
            if has_changeover and setting != decision["item"]:
                count += 1
            setting = decision["item"]
        changeovers[line_id] = count
    return changeovers


def space_change(item_id: str, recipe: str, planning: PlanningInput) -> Decimal:
    """Give the change of space held per unit a production of an item starts.

    Args:
        item_id (str): The identifier of the item made.
        recipe (str): The name of its recipe.
        planning (PlanningInput): The planning input.

    Returns:
        Decimal: The space of the item less the space of its inputs.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     Cash,
        ...     Item,
        ...     WindowStart,
        ... )
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     lines={},
        ...     warehouses={},
        ...     items={
        ...         "board": Item(
        ...             space=Decimal("0.02"),
        ...             storage_cost=Decimal(0),
        ...             salvage_value=Decimal(0),
        ...             recipes={"standard": {}},
        ...         )
        ...     },
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> space_change("board", "standard", planning)
        Decimal('0.02')
    """
    item = planning.items[item_id]
    inputs = sum(
        (
            quantity * planning.items[input_id].space
            for input_id, quantity in sorted(item.recipes[recipe].items())
        ),
        Decimal(0),
    )
    return item.space - inputs


def unit_space(decision: JsonObject, planning: PlanningInput) -> Decimal:
    """Give the space a decision adds per unit in the warehouse it is checked in.

    Args:
        decision (dict[str, Any]): The decision.
        planning (PlanningInput): The planning input of the period.

    Returns:
        Decimal: The space of the item of a buy or a transfer; the space of the item
            of a production less the space of its inputs; 0 for any other decision.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> unit_space({"kind": "repair", "line": "line-1"}, planning)
        Decimal('0')
    """
    if decision["kind"] == "buy":
        return planning.items[decision["material"]].space
    if decision["kind"] == "transfer":
        return planning.items[decision["item"]].space
    if decision["kind"] == "produce":
        return space_change(decision["item"], decision["recipe"], planning)
    return Decimal(0)


def check_and_fit(
    check: Check,
    decisions: list[JsonObject],
    planning: PlanningInput,
    history: list[JsonObject] | None = None,
) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    """Check decisions, and fit the first one the fit changes until none changes.

    A decision can be rejected only because an earlier one of the same check was,
    so after the fit of the first decision it changes, the decisions are checked
    again and the fit reads the new check. A decision fitted for an input or space it
    lacks is fitted again while the check rejects it for an input or space: a
    production keeps the most every input allows, and one whose inputs, rounded up,
    free less space at the fitted quantity is fitted until it fits. A decision is
    fitted once for each other reason: a buy fitted for space and then rejected for
    its credit is fitted for its credit too.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period.
        decisions (list[dict[str, Any]]): The decisions of a solution, in the order
            sent.
        planning (PlanningInput): The planning input of the period, whose first
            period is the period checked.
        history (list[dict[str, Any]] | None, optional): Receives each check input and
            its outcomes in call order, changed in place.

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]: The
            decisions the last check accepts; the dropped ones, each `{"period",
            "decision", "reason"}`; and the fitted ones, each `{"period", "decision",
            "reason", "before", "after"}`, `after` 0 for one left out.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import Cash, WindowStart
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> repair = {"kind": "repair", "line": "line-1", "amount": Decimal("0.1")}
        >>> accepted = [{"decision_id": "1-1", "accepted": True}]
        >>> check_and_fit(lambda period, decisions: accepted, [repair], planning)
        ([{'kind': 'repair', 'line': 'line-1', 'amount': Decimal('0.1')}], [], [])
    """
    period = planning.first_period
    if history is not None:
        history.append({"decisions": deepcopy(decisions), "outcomes": None})
    outcomes = check(period, decisions)
    if history is not None:
        history[-1]["outcomes"] = deepcopy(outcomes)
    fitted: list[JsonObject] = []
    # Every decision before the last one fitted is accepted and stays as it is.
    last_fitted = -1
    last_reasons: set[str] = set()
    changes = fitted_quantities(decisions, outcomes, planning)
    while changes:
        position = min(changes)
        reason, quantity = changes[position]
        # A production fitted to one input it lacks can lack another one. Its inputs
        # leave stock rounded up at each quantity, so at the fitted quantity they can
        # free less space beyond its space per unit than at the quantity checked, and
        # it can still lack space. Each fit takes at least 0.001 units, so fitting
        # again for inputs or space ends. The check of a buy in step 5 of a period
        # reads its space before its credit, so a buy fitted for space can lack credit;
        # a decision is fitted once for each other reason.
        if position < last_fitted or (
            position == last_fitted
            and reason in last_reasons
            and reason not in ("not_enough_input", "not_enough_space")
        ):
            break
        fitted.append(
            {
                "period": period,
                "decision": decisions[position],
                "reason": reason,
                "before": decisions[position]["quantity"],
                "after": quantity,
            }
        )
        kept = decisions[position + 1 :]
        decisions = fit_rejected(decisions[: position + 1], outcomes, planning) + kept
        # A decision fitted to 0 is left out, and the next one takes its position.
        if quantity == 0:
            last_fitted, last_reasons = position - 1, set[str]()
        elif position == last_fitted:
            last_reasons.add(reason)
        else:
            last_fitted, last_reasons = position, {reason}
        if history is not None:
            history.append({"decisions": deepcopy(decisions), "outcomes": None})
        outcomes = check(period, decisions)
        if history is not None:
            history[-1]["outcomes"] = deepcopy(outcomes)
        changes = fitted_quantities(decisions, outcomes, planning)
    dropped = [
        {
            "period": period,
            "decision": decisions[position_of(outcome)],
            "reason": outcome["reason"],
        }
        for outcome in outcomes
        if not outcome["accepted"]
    ]
    return keep_accepted(decisions, outcomes), dropped, fitted


def position_of(outcome: JsonObject) -> int:
    """Give the position from 0 of the decision of an outcome among those checked.

    Args:
        outcome (dict[str, Any]): The outcome; the n of its `decision_id` `<period>-<n>`
            counts the decisions from 1.

    Returns:
        int: n less 1.

    Examples:
        >>> position_of({"decision_id": "3-2"})
        1
    """
    return int(outcome["decision_id"].split("-")[1]) - 1


def keep_accepted(
    decisions: list[JsonObject], outcomes: list[JsonObject]
) -> list[JsonObject]:
    """Keep the decisions whose outcome of a check is accepted.

    A rejected decision changes nothing, so the kept decisions give the same outcomes
    again.

    Args:
        decisions (list[dict[str, Any]]): The decisions checked, in the order sent.
        outcomes (list[dict[str, Any]]): Their outcomes.

    Returns:
        list[dict[str, Any]]: The accepted decisions, in the order sent.

    Examples:
        >>> decisions = [{"kind": "repair"}, {"kind": "buy"}]
        >>> outcomes = [
        ...     {"decision_id": "3-1", "accepted": False},
        ...     {"decision_id": "3-2", "accepted": True},
        ... ]
        >>> keep_accepted(decisions, outcomes)
        [{'kind': 'buy'}]
    """
    accepted = {position_of(outcome) for outcome in outcomes if outcome["accepted"]}
    return [
        decision for position, decision in enumerate(decisions) if position in accepted
    ]


def fit_rejected(
    decisions: list[JsonObject], outcomes: list[JsonObject], planning: PlanningInput
) -> list[JsonObject]:
    """Fit the decisions a check rejected for lack of an input, space or credit.

    `fitted_quantities` gives the quantities; a decision fitted to 0 is left out.

    Args:
        decisions (list[dict[str, Any]]): The decisions checked, in the order sent.
        outcomes (list[dict[str, Any]]): Their outcomes.
        planning (PlanningInput): The planning input of the period.

    Returns:
        list[dict[str, Any]]: The decisions, the fitted ones changed, in the order sent.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     Cash,
        ...     Item,
        ...     WindowStart,
        ... )
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> board = Item(
        ...     space=Decimal(0),
        ...     storage_cost=Decimal(0),
        ...     salvage_value=Decimal(0),
        ...     recipes={"standard": {"chip": Decimal(2)}},
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={"board": board},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> produce = {
        ...     "kind": "produce",
        ...     "item": "board",
        ...     "recipe": "standard",
        ...     "quantity": Decimal("10.000"),
        ... }
        >>> outcome = {
        ...     "decision_id": "1-1",
        ...     "accepted": False,
        ...     "reason": "not_enough_input",
        ...     "item": "chip",
        ...     "asked": Decimal("20.000"),
        ...     "available": Decimal("19.995"),
        ... }
        >>> fit_rejected([produce], [outcome], planning)[0]["quantity"]
        Decimal('9.997')
    """
    changes = fitted_quantities(decisions, outcomes, planning)
    fitted = [
        decision | {"quantity": changes[position][1]}
        if position in changes
        else decision
        for position, decision in enumerate(decisions)
    ]
    return [decision for decision in fitted if decision.get("quantity", 1) > 0]


def fitted_quantities(
    decisions: list[JsonObject], outcomes: list[JsonObject], planning: PlanningInput
) -> dict[int, tuple[str, Decimal]]:
    """Give the quantity the fit gives every decision it changes, with its reason.

    Inputs leave stock rounded up to 3 places, and decisions that free space or bring
    cash are rounded down, so the decisions of a solution can ask for 0.001 units more
    than the check finds. A production short of an input gets `available` over the units
    of that input per unit, the most that input allows; a decision short of space loses
    `asked - available` over the space it adds per unit and keeps at least 0. The buys
    from the first one rejected `over_credit_limit` on, in the order sent, share the
    `available` of that buy: each gets at most the quantity the money left pays for at
    its unit price above 0, and the money left falls by its cost. A buy rejected for a
    reason the fit does not change uses no money. Every quantity is rounded down to 3
    places; a buy fitted below the larger of its minimum quantity and the `from` of the
    tier it was priced at gets 0.

    Args:
        decisions (list[dict[str, Any]]): The decisions checked, in the order sent.
        outcomes (list[dict[str, Any]]): Their outcomes.
        planning (PlanningInput): The planning input of the period.

    Returns:
        dict[int, tuple[str, Decimal]]: The reason and the fitted quantity of every
            decision whose quantity changes, by its position from 0.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     Cash,
        ...     Item,
        ...     WindowStart,
        ... )
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> board = Item(
        ...     space=Decimal(0),
        ...     storage_cost=Decimal(0),
        ...     salvage_value=Decimal(0),
        ...     recipes={"standard": {"chip": Decimal(2)}},
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={"board": board},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ... )
        >>> produce = {
        ...     "kind": "produce",
        ...     "item": "board",
        ...     "recipe": "standard",
        ...     "quantity": Decimal("10.000"),
        ... }
        >>> outcome = {
        ...     "decision_id": "1-1",
        ...     "accepted": False,
        ...     "reason": "not_enough_input",
        ...     "item": "chip",
        ...     "asked": Decimal("20.000"),
        ...     "available": Decimal("19.995"),
        ... }
        >>> fitted_quantities([produce], [outcome], planning)
        {0: ('not_enough_input', Decimal('9.997'))}
    """
    by_position = {position_of(outcome): outcome for outcome in outcomes}
    changes: dict[int, tuple[str, Decimal]] = {}
    money: Decimal | None = None
    for position, decision in enumerate(decisions):
        outcome = by_position[position]
        quantity = decision.get("quantity")
        if quantity is None:
            continue
        # A buy accepted after the first one rejected for its credit is fitted to
        # the money left, for the same reason.
        reason = outcome.get("reason", "over_credit_limit")
        fitted = quantity
        if not outcome["accepted"]:
            if reason == "not_enough_input":
                recipe = planning.items[decision["item"]].recipes[decision["recipe"]]
                fitted = outcome["available"] / recipe[outcome["item"]]
            elif reason == "not_enough_space" and unit_space(decision, planning) > 0:
                space = unit_space(decision, planning)
                missing = (outcome["asked"] - outcome["available"]) / space
                fitted = max(quantity - missing, Decimal(0))
            elif reason == "over_credit_limit":
                money = Decimal(outcome["available"]) if money is None else money
            else:
                continue
        fitted = fitted.quantize(QUANTITY_EXPONENT, rounding=ROUND_FLOOR)
        if decision["kind"] == "buy" and money is not None:
            unit_price, floor = buy_terms(decision, planning)
            if unit_price > 0:
                affordable = max(money, Decimal(0)) / unit_price
                fitted = min(
                    fitted, affordable.quantize(QUANTITY_EXPONENT, rounding=ROUND_FLOOR)
                )
            if fitted < floor:
                fitted = Decimal(0)
            money -= fitted * unit_price
        elif decision["kind"] == "buy" and fitted != quantity:
            if fitted < buy_terms(decision, planning)[1]:
                fitted = Decimal(0)
        if fitted != quantity:
            changes[position] = (reason, fitted)
    return changes


def buy_terms(decision: JsonObject, planning: PlanningInput) -> tuple[Decimal, Decimal]:
    """Give the unit price of a buy decision and the smallest quantity it may keep.

    Args:
        decision (dict[str, Any]): The buy decision.
        planning (PlanningInput): The planning input of the period.

    Returns:
        tuple[Decimal, Decimal]: The price of the tier of its quantity, from the buy
            option of the first period, and the larger of the minimum quantity of the
            option and the `from` of that tier.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     BuyOption,
        ...     Cash,
        ...     WindowStart,
        ... )
        >>> state = WindowStart(
        ...     cash=Decimal(1000),
        ...     stock={},
        ...     conditions={},
        ...     hours={},
        ...     production=(),
        ...     transfers=(),
        ...     supplier_orders=(),
        ...     receivables=(),
        ... )
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal(0),
        ...     debit_interest=Decimal(0),
        ...     overdraft_interest=Decimal(0),
        ... )
        >>> planning = PlanningInput(
        ...     first_period=1,
        ...     window_end=1,
        ...     horizon=1,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     customers={},
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(
        ...         BuyOption(
        ...             supplier="chip-maker",
        ...             material="chip",
        ...             period=1,
        ...             express=False,
        ...             unit_price=Decimal("0.5000"),
        ...             limit=Decimal(1000),
        ...             arrivals=(),
        ...         ),
        ...     ),
        ... )
        >>> buy = {
        ...     "supplier": "chip-maker",
        ...     "material": "chip",
        ...     "express": False,
        ...     "quantity": Decimal(20),
        ... }
        >>> buy_terms(buy, planning)
        (Decimal('0.5000'), Decimal('0'))
    """
    option = next(
        option
        for option in planning.buy_options
        if option.supplier == decision["supplier"]
        and option.material == decision["material"]
        and option.period == planning.first_period
        and option.express == decision["express"]
    )
    reached = [tier for tier in option.tiers if tier.from_ <= decision["quantity"]]
    if not reached:
        return option.unit_price, option.min_quantity
    return reached[-1].unit_price, max(option.min_quantity, reached[-1].from_)
