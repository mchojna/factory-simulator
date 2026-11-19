"""The profit program: a linear or mixed-integer program of a window, solved with HiGHS.

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
    ...     credit_interest=Decimal("0.01"),
    ...     debit_interest=Decimal("0.01"),
    ...     overdraft_interest=Decimal("0.01"),
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
    >>> round(solve_program(planning).value, 6)
    10.0
"""

import math
import time
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, linprog, milp
from scipy.sparse import coo_array

from factory_simulator.benchmark.models.inputs import (
    Arrival,
    BuyOption,
    CustomerOrder,
    PlanningInput,
    Route,
)
from factory_simulator.benchmark.models.outputs import (
    IntegerSolve,
    LinearSolve,
    Solution,
    SolutionBuy,
    SolutionProduce,
    SolutionRepair,
    SolutionShip,
    SolutionTransfer,
)

# A solution leaves out values at most this small; they round down to 0 anyway.
NOISE = 1e-9
# The most the engine can round in favor of the factory: good units half to even,
# inputs up, and accepted units of a delivery after three roundings half to even.
GOOD_ROUNDING = 0.0005
INPUT_ROUNDING = 0.001
ACCEPTED_ROUNDING = 0.0015
# The space rows keep free, per warehouse, this share of a unit of every item it
# accepts, for decisions that free space and are rounded down.
SPACE_ROUNDING = 0.001
# HiGHS keeps every row to within this, below the tolerance of 1e-9 that decisions
# add before they round down, so no rounded decision passes a limit of the program.
FEASIBILITY_TOLERANCE = 1e-10
# A solve of an integer program stops at this many nodes of HiGHS, or when the bound
# of its program exceeds the value of its solution by at most this many units of
# money; both count work, so a solve repeats on every machine.
NODE_LIMIT = 1000
GAP_LIMIT = 0.01
# Seconds one solve may take at most.
TIME_LIMIT = 600.0
# The share of the time limit of an integer solve that `milp` leaves to the linear
# program with the binaries fixed.
FIXED_RESERVE = 0.1
# The most binary variables an exact program may have: it is for small worlds only.
EXACT_BINARY_LIMIT = 100
# The credit row of a period without buys holds with this much cash to spare at the
# lowest cash the program can reach, or with a share of 1 / LARGEST_NUMBER of the
# amounts of the row when that is more, so the rounding of floats never makes it bind.
DEFICIT_MARGIN = 1.0
# HiGHS reads no number of a program above this, in the unit of money of the program:
# a power of ten, at least 1, that brings every amount of money down to it.
LARGEST_NUMBER = 1e9
# HiGHS drops a coefficient of a row at most this small.
SMALLEST_COEFFICIENT = 1e-9
# The variables that hold money: the cash at the close of every period.
MONEY_VARIABLES = ("cash_positive", "cash_debit", "cash_overdraft")

type Key = tuple[object, ...]
"""The key of a variable of a program: its kind, then the names and periods it is of."""
type StockKey = tuple[str, str, int]
"""The key of the stock of an item: its warehouse, its item and its period."""


class UnsupportedScaleError(ValueError):
    """A program whose numbers lie outside the numerical scale HiGHS solves.

    Examples:
        >>> isinstance(UnsupportedScaleError("period 1: ..."), ValueError)
        True
    """


@dataclass(slots=True, kw_only=True)
class Expression:
    """A linear expression: variables with their coefficients, plus a constant.

    Attributes:
        terms (dict[int, float]): The coefficient of each variable by its index.
        constant (float): The constant.

    Examples:
        >>> expression = Expression()
        >>> expression.add(0, 2.0)
        >>> expression.add(0, 1.5)
        >>> expression.terms, expression.constant
        ({0: 3.5}, 0.0)
    """

    terms: dict[int, float] = field(default_factory=dict[int, float])
    constant: float = 0.0

    def add(self, variable: int, coefficient: float) -> None:
        """Add a coefficient to a variable.

        Args:
            variable (int): The index of the variable.
            coefficient (float): The coefficient to add.

        Examples:
            >>> expression = Expression()
            >>> expression.add(3, -1.0)
            >>> expression.terms
            {3: -1.0}
        """
        self.terms[variable] = self.terms.get(variable, 0.0) + coefficient


def _combine(*parts: tuple[Expression, float]) -> Expression:
    """Combine expressions, each times a factor, into their sum.

    Args:
        *parts (tuple[Expression, float]): Each expression with its factor.

    Returns:
        Expression: The sum.
    """
    total = Expression()
    for expression, factor in parts:
        for variable, coefficient in expression.terms.items():
            total.add(variable, coefficient * factor)
        total.constant += expression.constant * factor
    return total


@dataclass(slots=True, kw_only=True)
class Program:
    """A linear program being built: variables with upper bounds, rows, objective.

    Attributes:
        variables (dict[tuple[object, ...], int]): The index of every variable by its
            key.
        upper_bounds (list[float]): The upper bound of every variable.
        objective (Expression): The objective, maximized.
        at_most_rows (list[tuple[dict[int, float], float]]): Rows `terms <= bound`.
        equal_rows (list[tuple[dict[int, float], float]]): Rows `terms == value`.
        binaries (set[int]): The indexes of the variables that are 0 or 1.
        last_binary_period (int): The last period whose choices are binary; the
            choices of later periods take any value from 0 to 1.
        rounding (bool): Whether the program allows the units the engine may round in
            favor of the factory, as `solve_relaxed` does.
        money_at_most_rows (set[int]): The positions of the rows `terms <= bound` of
            money.
        money_equal_rows (set[int]): The positions of the rows `terms == value` of
            money.

    Examples:
        >>> program = Program()
        >>> program.add_variable(("repair", "line-1", 1), upper=0.5)
        0
        >>> program.rounding
        False
    """

    variables: dict[Key, int] = field(default_factory=dict[Key, int])
    upper_bounds: list[float] = field(default_factory=list[float])
    objective: Expression = field(default_factory=Expression)
    at_most_rows: list[tuple[dict[int, float], float]] = field(
        default_factory=list[tuple[dict[int, float], float]]
    )
    equal_rows: list[tuple[dict[int, float], float]] = field(
        default_factory=list[tuple[dict[int, float], float]]
    )
    binaries: set[int] = field(default_factory=set[int])
    last_binary_period: int = 0
    rounding: bool = False
    money_at_most_rows: set[int] = field(default_factory=set[int])
    money_equal_rows: set[int] = field(default_factory=set[int])

    def add_variable(self, key: Key, upper: float = math.inf) -> int:
        """Add a variable from 0 to an upper bound.

        Args:
            key (tuple[object, ...]): The key of the variable, its kind first.
            upper (float, optional): The upper bound.

        Returns:
            int: The index of the variable.

        Examples:
            >>> Program().add_variable(("stock", "main", "chip", 1))
            0
        """
        self.variables[key] = len(self.upper_bounds)
        self.upper_bounds.append(upper)
        return self.variables[key]

    def add_binary(self, key: Key) -> int:
        """Add a variable that is 0 or 1.

        Args:
            key (tuple[object, ...]): The key of the variable, its kind first.

        Returns:
            int: The index of the variable.

        Examples:
            >>> program = Program()
            >>> program.add_binary(("order", "s", "chip", 1, False, "main"))
            0
            >>> program.binaries
            {0}
        """
        index = self.add_variable(key, upper=1.0)
        self.binaries.add(index)
        return index

    def add_choice(self, key: Key, period: int) -> int:
        """Add a choice of a period: binary up to `last_binary_period`, else 0 to 1.

        Args:
            key (tuple[object, ...]): The key of the variable, its kind first.
            period (int): The period of the choice.

        Returns:
            int: The index of the variable.

        Examples:
            >>> program = Program(last_binary_period=1)
            >>> program.add_choice(("order", "s", "chip", 2, False, "main"), 2)
            0
            >>> program.binaries
            set()
        """
        if period <= self.last_binary_period:
            return self.add_binary(key)
        return self.add_variable(key, upper=1.0)

    def add_at_most(
        self, expression: Expression, bound: float, money: bool = False
    ) -> None:
        """Add the row `expression <= bound`.

        Args:
            expression (Expression): The left side.
            bound (float): The right side.
            money (bool, optional): Whether the row counts money.

        Examples:
            >>> program = Program()
            >>> program.add_at_most(Expression(terms={0: 1.0}, constant=2.0), 5.0)
            >>> program.at_most_rows
            [({0: 1.0}, 3.0)]
        """
        if money:
            self.money_at_most_rows.add(len(self.at_most_rows))
        self.at_most_rows.append((expression.terms, bound - expression.constant))

    def add_equal(
        self, expression: Expression, value: float, money: bool = False
    ) -> None:
        """Add the row `expression == value`.

        Args:
            expression (Expression): The left side.
            value (float): The right side.
            money (bool, optional): Whether the row counts money.

        Examples:
            >>> program = Program()
            >>> program.add_equal(
            ...     Expression(terms={0: 1.0}, constant=2.0), 5.0, money=True
            ... )
            >>> program.equal_rows, program.money_equal_rows
            ([({0: 1.0}, 3.0)], {0})
        """
        if money:
            self.money_equal_rows.add(len(self.equal_rows))
        self.equal_rows.append((expression.terms, value - expression.constant))


@dataclass(slots=True, kw_only=True)
class StockFlows:
    """The flows of one item in one warehouse in one period.

    Attributes:
        available (Expression): Stock of the previous close plus what arrived.
        shipped (Expression): Shipments.
        sent (Expression): Transfers sent.
        arrived_at_once (Expression): Transfers sent to the warehouse with lead time
            0.
        inputs (Expression): Inputs of production started.
        good (Expression): Good units of production ready.

    Examples:
        >>> StockFlows().available
        Expression(terms={}, constant=0.0)
    """

    available: Expression = field(default_factory=Expression)
    shipped: Expression = field(default_factory=Expression)
    sent: Expression = field(default_factory=Expression)
    arrived_at_once: Expression = field(default_factory=Expression)
    inputs: Expression = field(default_factory=Expression)
    good: Expression = field(default_factory=Expression)


def solve_program(
    planning: PlanningInput,
    time_limit: float = TIME_LIMIT,
    exact: bool = False,
    *,
    diagnostics: list[IntegerSolve | LinearSolve] | None = None,
) -> Solution:
    """Solve the profit program of a window with HiGHS.

    A program with binary variables, for the credit choice of a buy in the first
    period, minimum quantities, discounts or changeovers, is solved with `milp`
    within its limits, its choices binary in the first period of the window only, or
    in every period of the window when it is exact; any other with `linprog`. HiGHS
    solves it with its money in the unit of `build_money_unit`; the value is in units
    of 1.

    Args:
        planning (PlanningInput): The planning input.
        time_limit (float, optional): Seconds the solve of an integer program may
            take.
        exact (bool, optional): Whether every choice of the window is binary.
        diagnostics (list[IntegerSolve | LinearSolve] | None, optional): Receives the
            report of every solve, in the order of the solves, changed in place.

    Returns:
        Solution: The value of the program and the decisions of the first period; no
            decision and the value None when an integer solve stops at a limit
            without a solution. The report of an integer solve is in money.

    Raises:
        RuntimeError: If HiGHS ends a linear program with a status other than
            optimal, or ends an integer program infeasible or unbounded.
        ValueError: If the program is exact and has more than `EXACT_BINARY_LIMIT`
            binary variables.
        UnsupportedScaleError: If the numbers of the program lie outside the scale of
            `build_money_unit`, naming the first period of the window.

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
        >>> rate = Decimal("0.01")
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=rate,
        ...     debit_interest=rate,
        ...     overdraft_interest=rate,
        ... )
        >>> empty = PlanningInput(
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
        >>> round(solve_program(empty).value, 6)
        10.0
    """
    program = build_program(planning, with_rounding=False, exact=exact)
    if exact and len(program.binaries) > EXACT_BINARY_LIMIT:
        raise ValueError(
            f"exact: the program has {len(program.binaries)} binary variables, "
            f"above {EXACT_BINARY_LIMIT}"
        )
    unit = build_money_unit(program, planning.first_period)
    in_unit = _in_money_unit(program, unit)
    if program.binaries:
        first = planning.first_period
        integer_diagnostics: list[IntegerSolve | LinearSolve] = []
        try:
            values, value, integer_solve = solve_integer(
                in_unit, time_limit, first, integer_diagnostics
            )
        except BaseException:
            if diagnostics is not None:
                diagnostics.extend(
                    _solve_in_money(record, unit) for record in integer_diagnostics
                )
            raise
        if diagnostics is not None:
            diagnostics.extend(
                _solve_in_money(record, unit) for record in integer_diagnostics
            )
        if values is None or value is None:
            return Solution(
                value=None,
                ships=(),
                transfers=(),
                repairs=(),
                produces=(),
                buys=(),
                integer_solve=_in_money(integer_solve, unit),
            )
        solution = _solution_of(program, planning, values, value * unit)
        return replace(solution, integer_solve=_in_money(integer_solve, unit))
    linear_diagnostics: list[LinearSolve] = []
    try:
        values, value, report = _solve_with_diagnostics(
            in_unit, diagnostics=linear_diagnostics
        )
    except BaseException:
        if diagnostics is not None:
            diagnostics.extend(
                replace(
                    record,
                    objective=(
                        None if record.objective is None else record.objective * unit
                    ),
                )
                for record in linear_diagnostics
            )
        raise
    if diagnostics is not None:
        diagnostics.extend(
            replace(
                record,
                objective=(
                    None if record.objective is None else record.objective * unit
                ),
            )
            for record in linear_diagnostics
        )
    solution = _solution_of(program, planning, values, value * unit)
    return replace(
        solution,
        linear_solve=replace(
            report,
            objective=(None if report.objective is None else report.objective * unit),
        ),
    )


def _in_money(integer_solve: IntegerSolve, unit: float) -> IntegerSolve:
    """Give the report of an integer solve in money from one in a unit of money.

    Args:
        integer_solve (IntegerSolve): The report, in the unit.
        unit (float): The unit of money of its program.

    Returns:
        IntegerSolve: The report with its value, bound and gap in money.
    """
    return replace(
        integer_solve,
        value=None if integer_solve.value is None else integer_solve.value * unit,
        bound=None if integer_solve.bound is None else integer_solve.bound * unit,
        gap=integer_solve.gap * unit,
        fixed_binary_solve=(
            None
            if integer_solve.fixed_binary_solve is None
            else replace(
                integer_solve.fixed_binary_solve,
                objective=(
                    None
                    if integer_solve.fixed_binary_solve.objective is None
                    else integer_solve.fixed_binary_solve.objective * unit
                ),
            )
        ),
    )


def _solve_in_money(
    record: IntegerSolve | LinearSolve, unit: float
) -> IntegerSolve | LinearSolve:
    """Give the report of a solve in money from one in a unit of money.

    Args:
        record (IntegerSolve | LinearSolve): The report, in the unit.
        unit (float): The unit of money of its program.

    Returns:
        IntegerSolve | LinearSolve: The report with its values in money.
    """
    if isinstance(record, IntegerSolve):
        return _in_money(record, unit)
    return replace(
        record,
        objective=None if record.objective is None else record.objective * unit,
    )


def solve_relaxed(
    planning: PlanningInput,
    diagnostics: list[LinearSolve] | None = None,
    time_limit: float | None = None,
) -> float:
    """Solve the relaxed program, binaries relaxed and rounding allowed; give its value.

    Every binary variable takes any value from 0 to 1, and the program has no credit
    rows. The engine rounds good and accepted units half to even and takes inputs
    rounded up, which can leave a run up to a thousandth of a unit better off than the
    program counts: each production may give up to 0.0005 good units more or fewer,
    never below 0, each input of it may leave up to 0.001 units more, and each arrival
    of a buy may bring up to 0.0015 accepted units more or fewer, wherever the engine
    can round. HiGHS solves it with its money in the unit of `build_money_unit`; the
    value is in units of 1.

    Args:
        planning (PlanningInput): The planning input.
        diagnostics (list[LinearSolve] | None, optional): Receives the report of the
            solve, changed in place.
        time_limit (float | None, optional): Seconds the linear solve may take.

    Returns:
        float: The value of the relaxed program.

    Raises:
        RuntimeError: If HiGHS ends with a status other than optimal, naming the
            first period of the window.
        TimeoutError: If HiGHS stops at the time limit.
        UnsupportedScaleError: If the numbers of the program lie outside the scale of
            `build_money_unit`, naming the first period of the window.

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
        >>> rate = Decimal("0.01")
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=rate,
        ...     debit_interest=rate,
        ...     overdraft_interest=rate,
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
        >>> round(solve_relaxed(planning), 6)
        10.0
    """
    program = build_program(planning, with_rounding=True)
    unit = build_money_unit(program, planning.first_period)
    try:
        _, value, report = _solve_with_diagnostics(
            _in_money_unit(program, unit),
            time_limit=time_limit,
            diagnostics=diagnostics,
        )
    except RuntimeError as error:
        if diagnostics:
            diagnostics[-1] = replace(
                diagnostics[-1],
                kind="linear_relaxed",
                objective=(
                    None
                    if diagnostics[-1].objective is None
                    else diagnostics[-1].objective * unit
                ),
            )
        raise RuntimeError(f"period {planning.first_period}: {error}") from error
    if diagnostics is not None:
        diagnostics[-1] = replace(report, kind="linear_relaxed", objective=value * unit)
    return value * unit


def build_money_unit(program: Program, period: int) -> float:
    """Build the unit of money in which HiGHS solves a program.

    The amounts of money of a program are the coefficients and right sides of its rows
    of money, the coefficients of its objective and the upper bounds of the variables
    that hold money; the constant of the objective is no part of them. The unit is the
    smallest power of ten, at least 1, that brings the largest of them down to at most
    `LARGEST_NUMBER`. A variable that holds money keeps its coefficient of 1 plus a
    rate. Every coefficient of money above `SMALLEST_COEFFICIENT` stays above it in the
    unit, so HiGHS drops none that it keeps in units of 1.

    Args:
        program (Program): The program.
        period (int): The first period of the window, named in an error.

    Returns:
        float: The unit of money.

    Raises:
        UnsupportedScaleError: If a number other than money, a coefficient, a right
            side or an upper bound, is above `LARGEST_NUMBER`, an amount of money is
            infinite, or a coefficient of money above `SMALLEST_COEFFICIENT` falls to
            it or below in the unit, naming the period.

    Examples:
        >>> program = Program()
        >>> cash = program.add_variable(("cash_positive", 1))
        >>> ship = program.add_variable(("ship", "order-1-1", "main", 1))
        >>> program.add_equal(
        ...     Expression(terms={cash: 1.0, ship: -5e12}), 0.0, money=True
        ... )
        >>> build_money_unit(program, 1)
        10000.0
    """
    money = _money_variables(program)
    money_rows: list[tuple[dict[int, float], float]] = []
    other_rows: list[tuple[dict[int, float], float]] = []
    for rows, money_positions in (
        (program.at_most_rows, program.money_at_most_rows),
        (program.equal_rows, program.money_equal_rows),
    ):
        for position, row in enumerate(rows):
            (money_rows if position in money_positions else other_rows).append(row)
    coefficients = [
        abs(coefficient)
        for terms in [terms for terms, _ in money_rows] + [program.objective.terms]
        for variable, coefficient in terms.items()
        if variable not in money
    ]
    amounts = coefficients + [abs(side) for _, side in money_rows]
    others = [abs(side) for _, side in other_rows] + [
        abs(coefficient) for terms, _ in other_rows for coefficient in terms.values()
    ]
    for variable, upper in enumerate(program.upper_bounds):
        if not math.isinf(upper):
            (amounts if variable in money else others).append(upper)
    largest_other = max(others, default=0.0)
    if largest_other > LARGEST_NUMBER:
        raise UnsupportedScaleError(
            f"period {period}: a number of the program other than money is "
            f"{largest_other:g}, above {LARGEST_NUMBER:g}"
        )
    largest = max(amounts, default=0.0)
    if math.isinf(largest):
        raise UnsupportedScaleError(
            f"period {period}: an amount of money of the program is {largest}"
        )
    unit = 1.0
    while largest / unit > LARGEST_NUMBER:
        unit *= 10
    kept = [
        coefficient
        for coefficient in coefficients
        if coefficient > SMALLEST_COEFFICIENT
    ]
    if kept and min(kept) / unit <= SMALLEST_COEFFICIENT:
        raise UnsupportedScaleError(
            f"period {period}: the money of the program runs from {min(kept):g} to "
            f"{largest:g}; in units of {unit:g} its smallest coefficient is "
            f"{min(kept) / unit:g}, at most {SMALLEST_COEFFICIENT:g}"
        )
    return unit


def _money_variables(program: Program) -> set[int]:
    """Give the variables that hold money.

    Args:
        program (Program): The program.

    Returns:
        set[int]: The index of every variable of a kind of `MONEY_VARIABLES`.
    """
    return {
        variable
        for key, variable in program.variables.items()
        if key[0] in MONEY_VARIABLES
    }


def _in_money_unit(program: Program, unit: float) -> Program:
    """Give a program with its money counted in a unit.

    A variable that holds money holds it in the unit, so its coefficients and its upper
    bound are those of the unit; the rows of money and the objective, its constant
    included, are then divided by the unit. Every other variable keeps its units.

    Args:
        program (Program): The program.
        unit (float): The unit of money.

    Returns:
        Program: The program in the unit.
    """
    money = _money_variables(program)

    def in_unit(terms: dict[int, float], divisor: float) -> dict[int, float]:
        return {
            variable: coefficient * (unit if variable in money else 1.0) / divisor
            for variable, coefficient in terms.items()
        }

    def rows_in_unit(
        rows: list[tuple[dict[int, float], float]], money_rows: set[int]
    ) -> list[tuple[dict[int, float], float]]:
        divisors = [
            unit if position in money_rows else 1.0 for position in range(len(rows))
        ]
        return [
            (in_unit(terms, divisor), side / divisor)
            for (terms, side), divisor in zip(rows, divisors, strict=True)
        ]

    objective = Expression(
        terms=in_unit(program.objective.terms, unit),
        constant=program.objective.constant / unit,
    )
    upper_bounds = [
        upper / unit if variable in money else upper
        for variable, upper in enumerate(program.upper_bounds)
    ]
    return replace(
        program,
        upper_bounds=upper_bounds,
        objective=objective,
        at_most_rows=rows_in_unit(program.at_most_rows, program.money_at_most_rows),
        equal_rows=rows_in_unit(program.equal_rows, program.money_equal_rows),
    )


def build_program(
    planning: PlanningInput, with_rounding: bool, exact: bool = False
) -> Program:
    """Build the variables, rows and objective of the profit program of a window.

    The choices of the first period of the window are binary, and those of every
    period when the program is exact. The objective is the profit of the run when the
    solution is followed, with no other term.

    Args:
        planning (PlanningInput): The planning input.
        with_rounding (bool): Whether to add the rounding of `solve_relaxed` and
            leave out the credit rows.
        exact (bool, optional): Whether every choice of the window is binary.

    Returns:
        Program: The program.

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
        >>> len(build_program(planning, with_rounding=False).equal_rows)
        1
    """
    last_binary_period = planning.window_end if exact else planning.first_period
    program = Program(last_binary_period=last_binary_period, rounding=with_rounding)
    _add_variables(program, planning)
    _add_changeover_variables(program, planning)
    if with_rounding:
        _add_rounding_variables(program, planning)
    flows = _stock_flows(program, planning)
    _add_stock_rows(program, flows)
    _add_order_rows(program, planning)
    _add_hour_rows(program, planning)
    _add_condition_rows(program, planning)
    _add_buy_rows(program, planning)
    _add_minimum_rows(program, planning)
    _add_tier_rows(program, planning)
    _add_purchase_budget_rows(program, planning)
    _add_changeover_rows(program, planning)
    _add_space_rows(program, planning, flows)
    before_buys, at_close, moved = _cash_flows(program, planning)
    _add_cash_rows(program, planning, before_buys, at_close, moved)
    _add_terminal_rows(program, planning)
    _add_rounding_rows(program, planning)
    _set_objective(program, planning)
    if not with_rounding:
        _add_credit_rows(program, planning, before_buys, at_close)
    return program


def _periods_of(planning: PlanningInput) -> range:
    """Give the periods of the window.

    Args:
        planning (PlanningInput): The planning input.

    Returns:
        range: From the first period to the end of the window.
    """
    return range(planning.first_period, planning.window_end + 1)


def _within_window(
    planning: PlanningInput, arrivals: tuple[Arrival, ...]
) -> tuple[Arrival, ...]:
    """Give the arrivals up to the end of the window.

    Args:
        planning (PlanningInput): The planning input.
        arrivals (tuple[Arrival, ...]): Arrivals of a supplier order or a buy.

    Returns:
        tuple[Arrival, ...]: Those whose period is at most `window_end`.
    """
    return tuple(
        arrival for arrival in arrivals if arrival.period <= planning.window_end
    )


def _ship_places(planning: PlanningInput) -> Iterator[tuple[CustomerOrder, str, int]]:
    """Give every order, warehouse and period a shipment can have.

    An order ships from every warehouse that accepts its product, from its arrival
    period to the earlier of its last period and the end of the window.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[CustomerOrder, str, int]: The order, the warehouse and the period.
    """
    for order in planning.customer_orders:
        first = max(order.arrival, planning.first_period)
        last = min(order.last, planning.window_end)
        for warehouse_id, warehouse in sorted(planning.warehouses.items()):
            if order.product in warehouse.accepts:
                for period in range(first, last + 1):
                    yield order, warehouse_id, period


def _make_places(
    planning: PlanningInput,
) -> Iterator[tuple[str, str, str, bool, int]]:
    """Give every line, item, recipe, hours and period a production can have.

    Overtime production exists only on a line with overtime hours above 0.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[str, str, str, bool, int]: The line, the item, the recipe, whether
            in overtime, and the period.
    """
    for line_id, line in sorted(planning.lines.items()):
        hours = [False, True] if line.overtime_hours > 0 else [False]
        for item_id in sorted(line.items):
            for recipe in sorted(planning.items[item_id].recipes):
                for overtime in hours:
                    for period in _periods_of(planning):
                        yield line_id, item_id, recipe, overtime, period


def _buy_places(planning: PlanningInput) -> Iterator[tuple[BuyOption, str]]:
    """Give every buy option with every warehouse that accepts its material.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[BuyOption, str]: The option and the warehouse.
    """
    for option in planning.buy_options:
        for warehouse_id, warehouse in sorted(planning.warehouses.items()):
            if option.material in warehouse.accepts:
                yield option, warehouse_id


def _transfer_places(planning: PlanningInput) -> Iterator[tuple[Route, str, int]]:
    """Give every route, item and period a transfer can have.

    An item is transferred along a route when both warehouses accept it.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[Route, str, int]: The route, the item and the period.
    """
    for route in planning.routes:
        destination = planning.warehouses[route.destination].accepts
        for item_id in planning.warehouses[route.source].accepts:
            if item_id not in destination:
                continue
            for period in _periods_of(planning):
                yield route, item_id, period


def _ship_key(order: CustomerOrder, warehouse_id: str, period: int) -> Key:
    """Give the key of a shipment variable.

    Args:
        order (CustomerOrder): The order.
        warehouse_id (str): The warehouse it leaves.
        period (int): The period.

    Returns:
        tuple[object, ...]: `("ship", order, warehouse, period)`.
    """
    return ("ship", order.id, warehouse_id, period)


def _buy_key(option: BuyOption, warehouse_id: str) -> Key:
    """Give the key of a buy variable.

    Args:
        option (BuyOption): The buy option.
        warehouse_id (str): The warehouse it goes to.

    Returns:
        tuple[object, ...]: `("buy", supplier, material, period, express, warehouse)`.
    """
    return (
        "buy",
        option.supplier,
        option.material,
        option.period,
        option.express,
        warehouse_id,
    )


def _transfer_key(route: Route, item_id: str, period: int) -> Key:
    """Give the key of a transfer variable.

    Args:
        route (Route): The route.
        item_id (str): The item.
        period (int): The period.

    Returns:
        tuple[object, ...]: `("transfer", source, destination, item, period)`.
    """
    return ("transfer", route.source, route.destination, item_id, period)


def _add_variables(program: Program, planning: PlanningInput) -> None:
    """Add every variable of the program.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    for order, warehouse_id, period in _ship_places(planning):
        program.add_variable(_ship_key(order, warehouse_id, period))
    for place in _make_places(planning):
        program.add_variable(("make", *place))
    for option, warehouse_id in _buy_places(planning):
        program.add_variable(_buy_key(option, warehouse_id))
    for route, item_id, period in _transfer_places(planning):
        program.add_variable(_transfer_key(route, item_id, period))
    for line_id, line in sorted(planning.lines.items()):
        for period in _periods_of(planning):
            program.add_variable(("repair", line_id, period), float(line.repair_limit))
            if period > planning.first_period:
                program.add_variable(("condition", line_id, period))
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        for item_id in sorted(warehouse.accepts):
            for period in _periods_of(planning):
                program.add_variable(("stock", warehouse_id, item_id, period))
    for period in _periods_of(planning):
        program.add_variable(("cash_positive", period))
        program.add_variable(("cash_debit", period), float(planning.cash.credit_limit))
        program.add_variable(("cash_overdraft", period))
    for item_id, terminal in sorted(planning.terminal_values.items()):
        program.add_variable(("terminal_cost", item_id), float(terminal.expected_use))
        program.add_variable(("terminal_salvage", item_id))


def changeover_lines(planning: PlanningInput) -> list[str]:
    """Give the lines with a changeover time or cost on one of their items.

    Args:
        planning (PlanningInput): The planning input.

    Returns:
        list[str]: Their identifiers, sorted.

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
        >>> changeover_lines(planning)
        []
    """
    return sorted(
        line_id
        for line_id, line in planning.lines.items()
        if any(
            item.changeover_time > 0 or item.changeover_cost > 0
            for item in line.items.values()
        )
    )


def _add_changeover_variables(program: Program, planning: PlanningInput) -> None:
    """Add the choices `runs`, `set` and `changeover` of every changeover line and item.

    `runs` tells that the line makes the item in the period, `set` that it is set for
    the item at the close, and `changeover` that the period has a changeover to the
    item. They are binary up to `last_binary_period` and from 0 to 1 after it.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    for line_id in changeover_lines(planning):
        for item_id in sorted(planning.lines[line_id].items):
            for period in _periods_of(planning):
                for kind in ("runs", "set", "changeover"):
                    program.add_choice((kind, line_id, item_id, period), period)


def _stock_flows(
    program: Program, planning: PlanningInput
) -> dict[StockKey, StockFlows]:
    """Give the flows of every item each warehouse accepts in every period.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.

    Returns:
        dict[tuple[str, str, int], StockFlows]: The flows by warehouse, item and
            period.
    """
    first = planning.first_period
    flows: dict[StockKey, StockFlows] = {}
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        for item_id in warehouse.accepts:
            for period in _periods_of(planning):
                flows[warehouse_id, item_id, period] = StockFlows()
                available = flows[warehouse_id, item_id, period].available
                if period == first:
                    stock = planning.state.stock.get(warehouse_id, {})
                    available.constant = float(stock.get(item_id, 0))
                else:
                    before = ("stock", warehouse_id, item_id, period - 1)
                    available.add(program.variables[before], 1.0)
    for order in planning.state.supplier_orders:
        for arrival in _within_window(planning, order.arrivals):
            place = (order.warehouse, order.material, arrival.period)
            flows[place].available.constant += float(arrival.accepted)
    for transfer in planning.state.transfers:
        place = (transfer.destination, transfer.item, transfer.arrival)
        if place in flows:
            flows[place].available.constant += float(transfer.quantity)
    for option, warehouse_id in _buy_places(planning):
        variable = program.variables[_buy_key(option, warehouse_id)]
        for arrival in _within_window(planning, option.arrivals):
            place = (warehouse_id, option.material, arrival.period)
            flows[place].available.add(variable, float(arrival.accepted))
    for route, item_id, period in _transfer_places(planning):
        variable = program.variables[_transfer_key(route, item_id, period)]
        flows[route.source, item_id, period].sent.add(variable, 1.0)
        arrival = (route.destination, item_id, period + route.lead_time)
        if route.lead_time == 0:
            flows[arrival].arrived_at_once.add(variable, 1.0)
        elif arrival in flows:
            flows[arrival].available.add(variable, 1.0)
    for order, warehouse_id, period in _ship_places(planning):
        variable = program.variables[_ship_key(order, warehouse_id, period)]
        flows[warehouse_id, order.product, period].shipped.add(variable, 1.0)
    for line_id, item_id, recipe, overtime, period in _make_places(planning):
        variable = program.variables["make", line_id, item_id, recipe, overtime, period]
        line = planning.lines[line_id]
        for input_id, quantity in sorted(
            planning.items[item_id].recipes[recipe].items()
        ):
            flows[line.warehouse, input_id, period].inputs.add(
                variable, float(quantity)
            )
        line_item = line.items[item_id]
        ready = (line.warehouse, item_id, period + line_item.lead_time - 1)
        if ready in flows:
            share = float(line_item.good_shares[period])
            flows[ready].good.add(variable, share)
    for production in planning.state.production:
        place = (production.warehouse, production.item, production.ready)
        if place in flows:
            flows[place].good.constant += float(production.good)
    if not program.rounding:
        return flows
    for make in _good_roundings(planning):
        line_id, item_id, _, _, period = make
        line = planning.lines[line_id]
        ready = (line.warehouse, item_id, period + line.items[item_id].lead_time - 1)
        flows[ready].good.add(program.variables["good_more", *make], 1.0)
        flows[ready].good.add(program.variables["good_less", *make], -1.0)
    for make, input_id in _input_roundings(planning):
        line = planning.lines[make[0]]
        place = (line.warehouse, input_id, make[-1])
        variable = program.variables["input_rounding", *make, input_id]
        flows[place].inputs.add(variable, 1.0)
    for option, warehouse_id, arrival in _accepted_roundings(planning):
        key = (*_buy_key(option, warehouse_id)[1:], arrival.period)
        available = flows[warehouse_id, option.material, arrival.period].available
        available.add(program.variables["accepted_more", *key], 1.0)
        available.add(program.variables["accepted_less", *key], -1.0)
    return flows


def _add_stock_rows(program: Program, flows: dict[StockKey, StockFlows]) -> None:
    """Add the stock rows of every item each warehouse accepts in every period.

    Shipments and transfers sent are at most the available stock; with inputs they
    are at most the available stock plus transfers arrived at once, as transfers run
    before produce. The stock at the close balances the flows.

    Args:
        program (Program): The program, changed in place.
        flows (dict[tuple[str, str, int], StockFlows]): The flows by warehouse,
            item and period.
    """
    for (warehouse_id, item_id, period), flow in flows.items():
        taken = _combine((flow.shipped, 1), (flow.sent, 1))
        program.add_at_most(_combine((taken, 1), (flow.available, -1)), 0)
        used = _combine((taken, 1), (flow.inputs, 1))
        within = _combine((flow.available, 1), (flow.arrived_at_once, 1))
        program.add_at_most(_combine((used, 1), (within, -1)), 0)
        closing = _combine((within, 1), (used, -1), (flow.good, 1))
        stock = program.variables["stock", warehouse_id, item_id, period]
        program.add_equal(
            _combine((Expression(terms={stock: 1.0}), 1), (closing, -1)), 0
        )


def _add_order_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that keep the shipments of every order within its open quantity.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    shipped: dict[str, Expression] = defaultdict(Expression)
    for order, warehouse_id, period in _ship_places(planning):
        variable = program.variables[_ship_key(order, warehouse_id, period)]
        shipped[order.id].add(variable, 1.0)
    for order in planning.customer_orders:
        program.add_at_most(shipped[order.id], float(order.open_quantity))


def _production_hours(
    program: Program, planning: PlanningInput, overtime: bool
) -> dict[tuple[str, int], Expression]:
    """Give the regular or the overtime production hours of every line and period.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.
        overtime (bool): Whether to give overtime hours.

    Returns:
        dict[tuple[str, int], Expression]: The hours by line and period.
    """
    hours: dict[tuple[str, int], Expression] = defaultdict(Expression)
    for line_id, item_id, recipe, in_overtime, period in _make_places(planning):
        if in_overtime == overtime:
            variable = program.variables[
                "make", line_id, item_id, recipe, in_overtime, period
            ]
            time = planning.lines[line_id].items[item_id].time
            hours[line_id, period].add(variable, float(time))
    return hours


def _add_hour_rows(program: Program, planning: PlanningInput) -> None:
    """Add the three limits of hours of every line in every period.

    Regular production and changeover hours are at most `capacity * cut *
    condition`; regular production, changeover and repair hours at most `capacity *
    cut`; overtime hours at most `overtime_hours * cut * condition`. In the first
    period the limits are the hours available of the state.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    regular = _production_hours(program, planning, overtime=False)
    overtime = _production_hours(program, planning, overtime=True)
    for line_id in changeover_lines(planning):
        for item_id, item in sorted(planning.lines[line_id].items.items()):
            for period in _periods_of(planning):
                change = program.variables["changeover", line_id, item_id, period]
                regular[line_id, period].add(change, float(item.changeover_time))
    for line_id, line in sorted(planning.lines.items()):
        for period in _periods_of(planning):
            repair = program.variables["repair", line_id, period]
            with_repair = _combine((regular[line_id, period], 1))
            with_repair.add(repair, float(line.repair_time))
            if period == planning.first_period:
                hours = planning.state.hours[line_id]
                program.add_at_most(regular[line_id, period], float(hours.regular))
                program.add_at_most(with_repair, float(hours.repair))
                if line.overtime_hours > 0:
                    program.add_at_most(
                        overtime[line_id, period], float(hours.overtime)
                    )
                continue
            condition = program.variables["condition", line_id, period]
            cut = line.hour_shares[period]
            limit = _combine((regular[line_id, period], 1))
            limit.add(condition, -float(line.capacity * cut))
            program.add_at_most(limit, 0)
            program.add_at_most(with_repair, float(line.capacity * cut))
            if line.overtime_hours > 0:
                limit = _combine((overtime[line_id, period], 1))
                limit.add(condition, -float(line.overtime_hours * cut))
                program.add_at_most(limit, 0)


def _add_condition_rows(program: Program, planning: PlanningInput) -> None:
    """Add the wear, repair and breakdowns of the condition of every line.

    `condition[t + 1] = (condition[t] * (1 - wear_per_period) - wear_per_hour *
    hours[t] + repair[t]) * kept[t + 1]`, with production hours in regular and
    overtime; `condition[t] + repair[t]` is at most 1.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    regular = _production_hours(program, planning, overtime=False)
    overtime = _production_hours(program, planning, overtime=True)
    for line_id, line in sorted(planning.lines.items()):
        for period in _periods_of(planning):
            condition = Expression()
            if period == planning.first_period:
                condition.constant = float(planning.state.conditions[line_id])
            else:
                condition.add(program.variables["condition", line_id, period], 1.0)
            repair = program.variables["repair", line_id, period]
            program.add_at_most(
                _combine((condition, 1), (Expression(terms={repair: 1.0}), 1)), 1
            )
            if period == planning.window_end:
                continue
            kept = float(line.kept_conditions[period + 1])
            worn = _combine(
                (condition, float(1 - line.wear_per_period)),
                (regular[line_id, period], -float(line.wear_per_hour)),
                (overtime[line_id, period], -float(line.wear_per_hour)),
                (Expression(terms={repair: 1.0}), 1),
            )
            following = program.variables["condition", line_id, period + 1]
            program.add_equal(
                _combine((Expression(terms={following: 1.0}), 1), (worn, -kept)), 0
            )


def _add_buy_rows(program: Program, planning: PlanningInput) -> None:
    """Add the buy limit of every supplier, material and period.

    The buys of all options of a supplier and material placed in a period, express
    or not and into every warehouse, sum to at most the buy limit.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    bought: dict[tuple[str, str, int], Expression] = defaultdict(Expression)
    limits: dict[tuple[str, str, int], float] = {}
    for option, warehouse_id in _buy_places(planning):
        supply = (option.supplier, option.material, option.period)
        bought[supply].add(program.variables[_buy_key(option, warehouse_id)], 1.0)
        limits[supply] = float(option.limit)
    for supply, expression in bought.items():
        program.add_at_most(expression, limits[supply])


def _add_minimum_rows(program: Program, planning: PlanningInput) -> None:
    """Add a choice `order` to every buy with a minimum quantity: 0 or at least it.

    The choice is binary up to `last_binary_period` and from 0 to 1 after it. `buy >=
    min_quantity * order` and `buy <= limit * order`; each buy into each warehouse is
    its own supplier order.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    for option, warehouse_id in _buy_places(planning):
        if option.min_quantity <= 0 or option.tiers:
            continue
        key = _buy_key(option, warehouse_id)
        buy = program.variables[key]
        order = program.add_choice(("order", *key[1:]), option.period)
        program.add_at_most(
            Expression(terms={order: float(option.min_quantity), buy: -1.0}), 0
        )
        program.add_at_most(
            Expression(terms={buy: 1.0, order: -float(option.limit)}), 0
        )


def _price_steps(option: BuyOption) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Give the tiers of a buy option with the catalogue price as tier 0.

    Args:
        option (BuyOption): The buy option.

    Returns:
        list[tuple[Decimal, Decimal, Decimal]]: The smallest quantity, the largest
            quantity and the unit price of every tier: tier 0 from the minimum
            quantity, each up to the next `from` less 0.001, the last up to the buy
            limit.
    """
    froms = [option.min_quantity, *(tier.from_ for tier in option.tiers)]
    prices = [option.unit_price, *(tier.unit_price for tier in option.tiers)]
    uppers = [following - Decimal("0.001") for following in froms[1:]] + [option.limit]
    return list(zip(froms, uppers, prices, strict=True))


def _add_tier_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that split every buy with discount tiers into one quantity per tier.

    One tier at most takes the buy. The choices are binary up to `last_binary_period`
    and from 0 to 1 after it. Per tier k, a choice `tier_k` and a quantity `buy_k` with
    `from_k * tier_k <= buy_k <= upper_k * tier_k`; `buy = sum_k buy_k` and `sum_k
    tier_k <= 1`, so every unit pays the price of the tier of its buy (`_buy_price`).

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    for option, warehouse_id in _buy_places(planning):
        if not option.tiers:
            continue
        key = _buy_key(option, warehouse_id)
        split = Expression(terms={program.variables[key]: 1.0})
        chosen = Expression()
        for tier, (smallest, largest, _) in enumerate(_price_steps(option)):
            choice = program.add_choice(("tier", *key[1:], tier), option.period)
            units = program.add_variable(("buy_tier", *key[1:], tier))
            program.add_at_most(
                Expression(terms={choice: float(smallest), units: -1.0}), 0
            )
            program.add_at_most(
                Expression(terms={units: 1.0, choice: -float(largest)}), 0
            )
            split.add(units, -1.0)
            chosen.add(choice, 1.0)
        program.add_equal(split, 0)
        program.add_at_most(chosen, 1)


def _add_purchase_budget_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that keep the cost of the buys of each period within its cap.

    The cap is `purchase_budget_cap`; a planning input without it gets no rows.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    if planning.purchase_budget_cap is None:
        return
    for period in _periods_of(planning):
        value = Expression()
        for option, warehouse_id in _buy_places(planning):
            if option.period == period:
                price = _buy_price(program, option, warehouse_id)
                value = _combine((value, 1), (price, 1))
        program.add_at_most(value, float(planning.purchase_budget_cap), money=True)


def _buy_price(program: Program, option: BuyOption, warehouse_id: str) -> Expression:
    """Give what a buy costs when all it orders is accepted.

    Args:
        program (Program): The program with its variables.
        option (BuyOption): The buy option.
        warehouse_id (str): The warehouse it goes to.

    Returns:
        Expression: Its quantity times its unit price, or with tiers the quantity of
            every tier times the price of the tier.
    """
    key = _buy_key(option, warehouse_id)
    if not option.tiers:
        return Expression(terms={program.variables[key]: float(option.unit_price)})
    price = Expression()
    for tier, (_, _, unit_price) in enumerate(_price_steps(option)):
        price.add(program.variables["buy_tier", *key[1:], tier], float(unit_price))
    return price


def _add_changeover_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that count the changeovers of every changeover line.

    For items i and j of the line: a production needs `runs`; `sum_i set[i, t] <=
    1` and at least `runs[j, t]`; `set[i, t]` is at most `set[i, t - 1] + runs[i, t]`
    and at most `runs[i, t] + 1 - runs[j, t]`, and at least `set[i, t - 1] - sum_k
    runs[k, t]`; `changeover[i, t]` is at least `runs[i, t] - set[i, t - 1]` and at
    least `set[i, t] + runs[j, t] - 1`. Before the first period `set` is the item of
    the state.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    made: dict[tuple[str, str, int], Expression] = defaultdict(Expression)
    for line_id, item_id, recipe, overtime, period in _make_places(planning):
        variable = program.variables["make", line_id, item_id, recipe, overtime, period]
        made[line_id, item_id, period].add(variable, 1.0)
    for line_id in changeover_lines(planning):
        line = planning.lines[line_id]
        items = sorted(line.items)
        for period in _periods_of(planning):
            runs = {
                item_id: program.variables["runs", line_id, item_id, period]
                for item_id in items
            }
            setting = {
                item_id: program.variables["set", line_id, item_id, period]
                for item_id in items
            }
            change = {
                item_id: program.variables["changeover", line_id, item_id, period]
                for item_id in items
            }
            any_run = Expression(terms=dict.fromkeys(runs.values(), 1.0))
            all_set = Expression(terms=dict.fromkeys(setting.values(), 1.0))
            program.add_at_most(all_set, 1)
            for first in items:
                before = _set_for_item_before(program, planning, line_id, first, period)
                most = (line.capacity + line.overtime_hours) / line.items[first].time
                program.add_at_most(
                    _combine(
                        (made[line_id, first, period], 1),
                        (Expression(terms={runs[first]: -float(most)}), 1),
                    ),
                    0,
                )
                program.add_at_most(
                    _combine((Expression(terms={runs[first]: 1.0}), 1), (all_set, -1)),
                    0,
                )
                program.add_at_most(
                    _combine(
                        (Expression(terms={setting[first]: 1.0, runs[first]: -1.0}), 1),
                        (before, -1),
                    ),
                    0,
                )
                program.add_at_most(
                    _combine(
                        (before, 1),
                        (any_run, -1),
                        (Expression(terms={setting[first]: -1.0}), 1),
                    ),
                    0,
                )
                program.add_at_most(
                    _combine(
                        (Expression(terms={runs[first]: 1.0, change[first]: -1.0}), 1),
                        (before, -1),
                    ),
                    0,
                )
                for second in items:
                    if second != first:
                        program.add_at_most(
                            Expression(
                                terms={
                                    setting[first]: 1.0,
                                    runs[first]: -1.0,
                                    runs[second]: 1.0,
                                }
                            ),
                            1,
                        )
                        program.add_at_most(
                            Expression(
                                terms={
                                    setting[first]: 1.0,
                                    runs[second]: 1.0,
                                    change[first]: -1.0,
                                }
                            ),
                            1,
                        )


def _set_for_item_before(
    program: Program, planning: PlanningInput, line_id: str, item_id: str, period: int
) -> Expression:
    """Tell whether a line is set for an item before a period.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.
        line_id (str): The line.
        item_id (str): The item.
        period (int): The period.

    Returns:
        Expression: 1 or 0 from the state before the first period; the variable
            `set` of the previous period after it.
    """
    if period == planning.first_period:
        set_for = planning.state.set_for.get(line_id)
        return Expression(constant=float(item_id == set_for))
    return Expression(
        terms={program.variables["set", line_id, item_id, period - 1]: 1.0}
    )


def _left_open(arrivals: tuple[Arrival, ...], period: int, opened: Decimal) -> Decimal:
    """Give what a supplier order or a buy option holds open in a period.

    Args:
        arrivals (tuple[Arrival, ...]): Its arrivals, in order.
        period (int): The period.
        opened (Decimal): What it holds before its first arrival.

    Returns:
        Decimal: What the last arrival up to the period left open, or `opened`.
    """
    held = opened
    for arrival in arrivals:
        if arrival.period <= period:
            held = arrival.left_open
    return held


def _add_space_rows(
    program: Program, planning: PlanningInput, flows: dict[StockKey, StockFlows]
) -> None:
    """Add the space held in every warehouse in every period, as the checks count it.

    The transfers of a period run in the order of the routes, and each is checked
    before the next. While they run, the space held in a warehouse is at most its
    capacity before each transfer that leaves it and after the last transfer: the
    space after the shipments, of production not yet in stock, of open supplier orders
    and of transfers on the way, with the transfers run so far in and out. A row is
    left out where no transfer into the warehouse came since the last one. After every
    decision of the period the space held is at most the capacity too. The capacity
    of the rows is less a margin for decisions rounded down to 0.001: 0.001 times the
    sum of the space per unit of the items the warehouse accepts, at most the space
    free in the first period of the window without decisions.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
        flows (dict[tuple[str, str, int], StockFlows]): The flows by warehouse,
            item and period.
    """
    first, window_end = planning.first_period, planning.window_end
    space = {item_id: float(item.space) for item_id, item in planning.items.items()}
    held: dict[tuple[str, int], Expression] = defaultdict(Expression)
    added: dict[tuple[str, int], Expression] = defaultdict(Expression)
    for (warehouse_id, item_id, period), flow in flows.items():
        after_shipments = _combine((flow.available, 1), (flow.shipped, -1))
        held[warehouse_id, period] = _combine(
            (held[warehouse_id, period], 1), (after_shipments, space[item_id])
        )
        added[warehouse_id, period] = _combine(
            (added[warehouse_id, period], 1), (flow.inputs, -space[item_id])
        )
    for production in planning.state.production:
        for period in range(first, min(production.ready, window_end) + 1):
            held[production.warehouse, period].constant += float(
                production.started * planning.items[production.item].space
            )
    for line_id, item_id, recipe, overtime, started in _make_places(planning):
        variable = program.variables[
            "make", line_id, item_id, recipe, overtime, started
        ]
        line = planning.lines[line_id]
        ready = started + line.items[item_id].lead_time - 1
        added[line.warehouse, started].add(variable, space[item_id])
        for period in range(started + 1, min(ready, window_end) + 1):
            held[line.warehouse, period].add(variable, space[item_id])
    for order in planning.state.supplier_orders:
        for period in range(first, window_end + 1):
            units = _left_open(order.arrivals, period, order.open_quantity)
            held[order.warehouse, period].constant += (
                float(units) * space[order.material]
            )
    for option, warehouse_id in _buy_places(planning):
        variable = program.variables[_buy_key(option, warehouse_id)]
        added[warehouse_id, option.period].add(variable, space[option.material])
        for period in range(option.period + 1, window_end + 1):
            share = _left_open(option.arrivals, period, Decimal(1))
            held[warehouse_id, period].add(
                variable, float(share) * space[option.material]
            )
    for transfer in planning.state.transfers:
        for period in range(first, min(transfer.arrival - 1, window_end) + 1):
            held[transfer.destination, period].constant += (
                float(transfer.quantity) * space[transfer.item]
            )
    moved: dict[tuple[Route, int], Expression] = defaultdict(Expression)
    for route, item_id, sent in _transfer_places(planning):
        variable = program.variables[_transfer_key(route, item_id, sent)]
        moved[route, sent].add(variable, space[item_id])
        for period in range(sent + 1, min(sent + route.lead_time - 1, window_end) + 1):
            held[route.destination, period].add(variable, space[item_id])
    during = _space_during_transfers(planning, held, moved)
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        # The constant of an expression is the space held without decisions.
        free = float(warehouse.capacity) - held[warehouse_id, first].constant
        margin = SPACE_ROUNDING * sum(space[item_id] for item_id in warehouse.accepts)
        capacity = float(warehouse.capacity) - max(0.0, min(margin, free))
        for period in _periods_of(planning):
            peaks, after_transfers = during[warehouse_id, period]
            for peak in peaks:
                program.add_at_most(peak, capacity)
            after_all = _combine((after_transfers, 1), (added[warehouse_id, period], 1))
            program.add_at_most(after_all, capacity)


def _space_during_transfers(
    planning: PlanningInput,
    held: dict[tuple[str, int], Expression],
    moved: dict[tuple[Route, int], Expression],
) -> dict[tuple[str, int], tuple[list[Expression], Expression]]:
    """Give the space held in each warehouse at the peaks of the transfers of a period.

    The transfers run in the order of the routes. The space held in a warehouse peaks
    before a transfer leaves it and after the last transfer, unless no transfer into
    it came since the previous peak.

    Args:
        planning (PlanningInput): The planning input.
        held (dict[tuple[str, int], Expression]): The space held by warehouse and
            period before the transfers of the period.
        moved (dict[tuple[Route, int], Expression]): The space a route moves by route
            and period of sending.

    Returns:
        dict[tuple[str, int], tuple[list[Expression], Expression]]: By warehouse and
            period, the space held at each peak and after every transfer.
    """
    during: dict[tuple[str, int], tuple[list[Expression], Expression]] = {}
    for period in _periods_of(planning):
        running = {
            warehouse_id: held[warehouse_id, period]
            for warehouse_id in planning.warehouses
        }
        risen = dict.fromkeys(planning.warehouses, True)
        peaks: dict[str, list[Expression]] = {
            warehouse_id: [] for warehouse_id in planning.warehouses
        }
        for route in planning.routes:
            transfer = moved[route, period]
            # A transfer out frees space, so the space before it is a peak, unless
            # nothing came in since the last peak.
            if risen[route.source]:
                peaks[route.source].append(running[route.source])
                risen[route.source] = False
            running[route.source] = _combine((running[route.source], 1), (transfer, -1))
            running[route.destination] = _combine(
                (running[route.destination], 1), (transfer, 1)
            )
            risen[route.destination] = True
        for warehouse_id, expression in running.items():
            if risen[warehouse_id]:
                peaks[warehouse_id].append(expression)
            during[warehouse_id, period] = peaks[warehouse_id], expression
    return during


def _payment_period(planning: PlanningInput, order: CustomerOrder, shipped: int) -> int:
    """Give the period in which the revenue of a shipment is paid.

    Args:
        planning (PlanningInput): The planning input.
        order (CustomerOrder): The order shipped.
        shipped (int): The period of the shipment.

    Returns:
        int: The period of the shipment plus the payment terms of the customer.
    """
    return shipped + planning.customers[order.customer].payment_terms


def penalty_periods(
    planning: PlanningInput, order: CustomerOrder
) -> Iterator[tuple[int, Decimal]]:
    """Give every period of the window in which an order pays a penalty per unit.

    As the close of a period counts them: the late penalty in every period from the
    due period to the period before the one in which the order is lost, and the
    lost-sale penalty in that period, the earlier of its last period and the horizon
    once its due period has come. Only the periods up to the end of the window count.

    Args:
        planning (PlanningInput): The planning input.
        order (CustomerOrder): The order.

    Yields:
        tuple[int, Decimal]: The period and the penalty per unit not shipped.

    Examples:
        >>> from factory_simulator.benchmark.models.inputs import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
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
        ...     window_end=3,
        ...     horizon=3,
        ...     starting_cash=Decimal(1000),
        ...     items={},
        ...     lines={},
        ...     warehouses={},
        ...     routes=(),
        ...     cash=cash,
        ...     state=state,
        ...     customer_orders=(),
        ...     buy_options=(),
        ...     customers={
        ...         "shop": Customer(
        ...             payment_terms=0,
        ...             products={
        ...                 "bolt": CustomerProduct(
        ...                     price=Decimal(50),
        ...                     transport_cost=Decimal(1),
        ...                     late_penalty=Decimal(2),
        ...                     lost_sale_penalty=Decimal(10),
        ...                 )
        ...             },
        ...         )
        ...     },
        ... )
        >>> order = CustomerOrder(
        ...     id="order-1-1",
        ...     customer="shop",
        ...     product="bolt",
        ...     open_quantity=Decimal(4),
        ...     arrival=1,
        ...     due=1,
        ...     last=3,
        ... )
        >>> list(penalty_periods(planning, order))
        [(1, Decimal('2')), (2, Decimal('2')), (3, Decimal('10'))]
    """
    terms = planning.customers[order.customer].products[order.product]
    lost = min(order.last, planning.horizon) if order.due <= planning.horizon else None
    last_late = planning.window_end if lost is None else lost - 1
    for period in range(
        max(order.due, planning.first_period),
        min(last_late, planning.window_end) + 1,
    ):
        yield period, terms.late_penalty
    if lost is not None and planning.first_period <= lost <= planning.window_end:
        yield lost, terms.lost_sale_penalty


def _cash_after_interest(
    program: Program, planning: PlanningInput, period: int
) -> Expression:
    """Give the cash after interest at the close of a period.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.
        period (int): The period.

    Returns:
        Expression: `cash_positive * (1 + credit_interest) - cash_debit * (1 +
            debit_interest) - cash_overdraft * (1 + overdraft_interest)`.
    """
    rates = planning.cash
    return Expression(
        terms={
            program.variables["cash_positive", period]: float(
                1 + rates.credit_interest
            ),
            program.variables["cash_debit", period]: -float(1 + rates.debit_interest),
            program.variables["cash_overdraft", period]: -float(
                1 + rates.overdraft_interest
            ),
        }
    )


def _cash_flows(
    program: Program, planning: PlanningInput
) -> tuple[dict[int, Expression], dict[int, Expression], dict[int, Expression]]:
    """Give the cash flows of every period, split at the moment its buys are checked.

    The first part is what moves cash before the buys of the period are checked:
    payments of deliveries and receivables, and the shipments, transfers, repairs and
    productions of the period. The second part is what the close moves: storage and
    penalties. The third part is the payments of arrivals after the window, of open
    supplier orders and of buys, moved to the last period of the window.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.

    Returns:
        tuple[dict[int, Expression], dict[int, Expression], dict[int, Expression]]:
            The flows before the buys, the flows of the close and the moved
            payments, by period.
    """
    window_end = planning.window_end
    flows: dict[int, Expression] = defaultdict(Expression)
    closing: dict[int, Expression] = defaultdict(Expression)
    moved: dict[int, Expression] = defaultdict(Expression)
    for receivable in planning.state.receivables:
        flows[receivable.payment_period].constant += float(receivable.amount)
    for order, warehouse_id, period in _ship_places(planning):
        variable = program.variables[_ship_key(order, warehouse_id, period)]
        terms = planning.customers[order.customer].products[order.product]
        flows[_payment_period(planning, order, period)].add(
            variable, float(terms.price)
        )
        transport = (
            terms.transport_cost * planning.warehouses[warehouse_id].transport_factor
        )
        flows[period].add(variable, -float(transport))
    for order in planning.state.supplier_orders:
        for arrival in order.arrivals:
            paid = flows[arrival.period]
            if arrival.period > window_end:
                paid = moved[window_end]
            paid.constant -= float(arrival.accepted * order.unit_price)
    for option, warehouse_id in _buy_places(planning):
        price = _buy_price(program, option, warehouse_id)
        for arrival in option.arrivals:
            paid = flows[arrival.period]
            if arrival.period > window_end:
                paid = moved[window_end]
            for variable, coefficient in price.terms.items():
                paid.add(variable, -coefficient * float(arrival.accepted))
    for route, item_id, sent in _transfer_places(planning):
        variable = program.variables[_transfer_key(route, item_id, sent)]
        flows[sent].add(variable, -float(route.cost))
        storage = (
            planning.items[item_id].storage_cost
            * planning.warehouses[route.destination].storage_factor
        )
        for period in range(sent, min(sent + route.lead_time - 1, window_end) + 1):
            closing[period].add(variable, -float(storage))
    for transfer in planning.state.transfers:
        storage = (
            planning.items[transfer.item].storage_cost
            * planning.warehouses[transfer.destination].storage_factor
        )
        for period in range(
            planning.first_period, min(transfer.arrival - 1, window_end) + 1
        ):
            closing[period].constant -= float(transfer.quantity * storage)
    for line_id, line in sorted(planning.lines.items()):
        for period in _periods_of(planning):
            repair = program.variables["repair", line_id, period]
            flows[period].add(repair, -float(line.repair_cost))
    for line_id, item_id, recipe, overtime, period in _make_places(planning):
        variable = program.variables["make", line_id, item_id, recipe, overtime, period]
        line = planning.lines[line_id]
        cost = line.items[item_id].cost
        if overtime:
            cost += line.items[item_id].time * line.overtime_cost
        flows[period].add(variable, -float(cost))
    for line_id in changeover_lines(planning):
        for item_id, item in sorted(planning.lines[line_id].items.items()):
            for period in _periods_of(planning):
                change = program.variables["changeover", line_id, item_id, period]
                flows[period].add(change, -float(item.changeover_cost))
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        for item_id in warehouse.accepts:
            storage = planning.items[item_id].storage_cost * warehouse.storage_factor
            for period in _periods_of(planning):
                stock = program.variables["stock", warehouse_id, item_id, period]
                closing[period].add(stock, -float(storage))
    if program.rounding:
        for option, warehouse_id, arrival in _accepted_roundings(planning):
            key = (*_buy_key(option, warehouse_id)[1:], arrival.period)
            price = float(option.unit_price)
            flows[arrival.period].add(program.variables["accepted_more", *key], -price)
            flows[arrival.period].add(program.variables["accepted_less", *key], price)
    _add_penalties(program, planning, closing)
    return flows, closing, moved


def _cash_at_start(
    program: Program, planning: PlanningInput, period: int
) -> Expression:
    """Give the cash at the start of a period, before its flows.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.
        period (int): The period.

    Returns:
        Expression: The cash of the state in the first period, or the cash after
            interest of the previous close.
    """
    if period == planning.first_period:
        return Expression(constant=float(planning.state.cash))
    return _cash_after_interest(program, planning, period - 1)


def _add_cash_rows(
    program: Program,
    planning: PlanningInput,
    before_buys: dict[int, Expression],
    at_close: dict[int, Expression],
    moved: dict[int, Expression],
) -> None:
    """Add the cash before interest at the close of every period.

    It is the cash at the start of the period plus payments received less every
    cost of the period, and in the last period of the window the payments moved to
    it from arrivals after the window.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
        before_buys (dict[int, Expression]): The flows before the buys, by period.
        at_close (dict[int, Expression]): The flows of the close, by period.
        moved (dict[int, Expression]): The payments moved to the last period of the
            window, by period.
    """
    for period in _periods_of(planning):
        cash = Expression(
            terms={
                program.variables["cash_positive", period]: 1.0,
                program.variables["cash_debit", period]: -1.0,
                program.variables["cash_overdraft", period]: -1.0,
            }
        )
        program.add_equal(
            _combine(
                (cash, 1),
                (_cash_at_start(program, planning, period), -1),
                (before_buys[period], -1),
                (at_close[period], -1),
                (moved[period], -1),
            ),
            0,
            money=True,
        )


def _variable_ceilings(program: Program) -> list[float]:
    """Give the upper bound of every variable that its bounds and rows imply.

    Every variable is at least 0. A row `sum of a * x <= b` keeps each variable of
    coefficient a above 0 at most `(b - floor) / a`, the floor the sum of every
    coefficient below 0 times the upper bound of its variable. An equal row counts as
    two rows, one in each direction. The rows are read again until a pass bounds no
    variable that had no bound.

    Args:
        program (Program): The program with its rows.

    Returns:
        list[float]: The upper bound of every variable by its index, `math.inf` for a
            variable no row bounds.
    """
    ceilings = list(program.upper_bounds)
    rows = list(program.at_most_rows)
    for terms, value in program.equal_rows:
        negated = {variable: -coefficient for variable, coefficient in terms.items()}
        rows.append((terms, value))
        rows.append((negated, -value))
    bounded_more = True
    while bounded_more:
        bounded_more = False
        for terms, bound in rows:
            floor = sum(
                coefficient * ceilings[variable]
                for variable, coefficient in terms.items()
                if coefficient < 0
            )
            if math.isinf(floor):
                continue
            for variable, coefficient in terms.items():
                if coefficient <= 0:
                    continue
                ceiling = (bound - floor) / coefficient
                if ceiling < ceilings[variable]:
                    bounded_more = bounded_more or math.isinf(ceilings[variable])
                    ceilings[variable] = ceiling
    return ceilings


def _lowest(expression: Expression, ceilings: list[float]) -> float:
    """Give the lowest value of an expression, every variable from 0 to its ceiling.

    Args:
        expression (Expression): The expression.
        ceilings (list[float]): The upper bound of every variable by its index.

    Returns:
        float: The constant plus every coefficient below 0 times its ceiling.
    """
    terms = expression.terms.items()
    return expression.constant + sum(
        coefficient * ceilings[variable]
        for variable, coefficient in terms
        if coefficient < 0
    )


def _highest(expression: Expression, ceilings: list[float]) -> float:
    """Give the highest value of an expression, every variable from 0 to its ceiling.

    Args:
        expression (Expression): The expression.
        ceilings (list[float]): The upper bound of every variable by its index.

    Returns:
        float: The constant plus every coefficient above 0 times its ceiling.
    """
    terms = expression.terms.items()
    return expression.constant + sum(
        coefficient * ceilings[variable]
        for variable, coefficient in terms
        if coefficient > 0
    )


def _lowest_cash_before_buys(
    planning: PlanningInput,
    ceilings: list[float],
    before_buys: dict[int, Expression],
    at_close: dict[int, Expression],
) -> dict[int, float]:
    """Give the lowest cash before the buys of every period that the program can reach.

    From the cash of the state, each period adds its flows before the buys and then the
    flows of its close, each at its lowest. The cash at the close then earns the credit
    rate when it is at least 0, and pays the higher of the debit and overdraft rates
    on all of it when it is below 0, which is at most the interest the engine charges.
    The bound holds for every plan whose cash at the close splits as the engine charges
    interest on it; any other split only lowers cash.

    Args:
        planning (PlanningInput): The planning input.
        ceilings (list[float]): The upper bound of every variable by its index.
        before_buys (dict[int, Expression]): The flows before the buys, by period.
        at_close (dict[int, Expression]): The flows of the close, by period.

    Returns:
        dict[int, float]: The lowest cash before the buys, by period.
    """
    rates = planning.cash
    negative_rate = float(max(rates.debit_interest, rates.overdraft_interest))
    lowest: dict[int, float] = {}
    cash = float(planning.state.cash)
    for period in _periods_of(planning):
        lowest[period] = cash + _lowest(before_buys[period], ceilings)
        closed = lowest[period] + _lowest(at_close[period], ceilings)
        rate = float(rates.credit_interest) if closed >= 0 else negative_rate
        cash = closed * (1 + rate)
    return lowest


def _add_credit_rows(
    program: Program,
    planning: PlanningInput,
    before_buys: dict[int, Expression],
    at_close: dict[int, Expression],
) -> None:
    """Add the credit check of the buys of every period, as step 5 of a period does.

    A choice `credit_ok` of the period, binary up to `last_binary_period` and from 0 to
    1 after it, allows its buys: their cost is at most `credit_ok` times their largest
    cost, the buy limit of each buy option times its highest unit price, summed. What is
    owed plus the cost of the buys of the period, less the cash before the buys, is at
    most the credit limit plus the deficit bound times `1 - credit_ok`. The deficit
    bound of the period is the most that is owed less the lowest cash before the buys
    less the credit limit, at least 0, plus a margin: `DEFICIT_MARGIN`, or the size of
    the most owed, the lowest cash and the credit limit together divided by
    `LARGEST_NUMBER` when that is more. A period without buys then meets its row at
    every cash the program can reach. What is owed is the share left open of every open
    supplier order and of every buy placed before the period, at its unit price. The
    cash before the buys leaves out the payments moved to the last period of the window.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
        before_buys (dict[int, Expression]): The flows before the buys, by period.
        at_close (dict[int, Expression]): The flows of the close, by period.
    """
    limit = float(planning.cash.credit_limit)
    ceilings = _variable_ceilings(program)
    lowest_cash = _lowest_cash_before_buys(planning, ceilings, before_buys, at_close)
    for period in _periods_of(planning):
        places = [
            (option, warehouse_id)
            for option, warehouse_id in _buy_places(planning)
            if option.period == period
        ]
        if not places:
            continue
        allowed = program.add_choice(("credit_ok", period), period)
        cost = Expression()
        for option, warehouse_id in places:
            cost = _combine((cost, 1), (_buy_price(program, option, warehouse_id), 1))
        # The buys of an option into every warehouse share its buy limit.
        largest = sum(
            float(option.limit * max(price for _, _, price in _price_steps(option)))
            for option in planning.buy_options
            if option.period == period
        )
        program.add_at_most(
            _combine((cost, 1), (Expression(terms={allowed: 1.0}), -largest)),
            0,
            money=True,
        )
        owed = Expression()
        for order in planning.state.supplier_orders:
            units = _left_open(order.arrivals, period, order.open_quantity)
            owed.constant += float(units * order.unit_price)
        for option, warehouse_id in _buy_places(planning):
            if option.period < period:
                share = _left_open(option.arrivals, period, Decimal(1))
                price = _buy_price(program, option, warehouse_id)
                owed = _combine((owed, 1), (price, float(share)))
        cash = _combine(
            (_cash_at_start(program, planning, period), 1), (before_buys[period], 1)
        )
        most_owed = _highest(owed, ceilings)
        deficit = most_owed - lowest_cash[period] - limit
        amounts = abs(most_owed) + abs(lowest_cash[period]) + limit
        bound = max(0.0, deficit) + max(DEFICIT_MARGIN, amounts / LARGEST_NUMBER)
        program.add_at_most(
            _combine(
                (owed, 1),
                (cost, 1),
                (cash, -1),
                (Expression(terms={allowed: bound}), 1),
            ),
            limit + bound,
            money=True,
        )


def _add_penalties(
    program: Program, planning: PlanningInput, flows: dict[int, Expression]
) -> None:
    """Add the late and lost-sale penalties of every order to the cash flows.

    A penalty of a period is the open quantity less the shipments up to the period,
    times the penalty per unit.

    Args:
        program (Program): The program with its variables.
        planning (PlanningInput): The planning input.
        flows (dict[int, Expression]): The cash flow of every period, changed in
            place.
    """
    shipments: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for order, warehouse_id, period in _ship_places(planning):
        variable = program.variables[_ship_key(order, warehouse_id, period)]
        shipments[order.id].append((period, variable))
    for order in planning.customer_orders:
        for period, penalty in penalty_periods(planning, order):
            flows[period].constant -= float(order.open_quantity * penalty)
            for shipped, variable in shipments[order.id]:
                if shipped <= period:
                    flows[period].add(variable, float(penalty))


def _add_terminal_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that split the units of every item with a terminal value at the end.

    The end is the end of the window. The units at the end are the stock at the close of
    the window, the good units of production ready after it, the accepted units of
    arrivals after it, and the units of transfers that arrive after it and by the
    horizon; they are `terminal_cost` plus `terminal_salvage`.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    window_end = planning.window_end
    units: dict[str, Expression] = defaultdict(Expression)
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        for item_id in warehouse.accepts:
            stock = program.variables["stock", warehouse_id, item_id, window_end]
            units[item_id].add(stock, 1.0)
    for production in planning.state.production:
        if production.ready > window_end:
            units[production.item].constant += float(production.good)
    for line_id, item_id, recipe, overtime, period in _make_places(planning):
        line_item = planning.lines[line_id].items[item_id]
        if period + line_item.lead_time - 1 > window_end:
            variable = program.variables[
                "make", line_id, item_id, recipe, overtime, period
            ]
            units[item_id].add(variable, float(line_item.good_shares[period]))
    for order in planning.state.supplier_orders:
        for arrival in order.arrivals:
            if arrival.period > window_end:
                units[order.material].constant += float(arrival.accepted)
    for option, warehouse_id in _buy_places(planning):
        variable = program.variables[_buy_key(option, warehouse_id)]
        for arrival in option.arrivals:
            if arrival.period > window_end:
                units[option.material].add(variable, float(arrival.accepted))
    for transfer in planning.state.transfers:
        if window_end < transfer.arrival <= planning.horizon:
            units[transfer.item].constant += float(transfer.quantity)
    for route, item_id, sent in _transfer_places(planning):
        if window_end < sent + route.lead_time <= planning.horizon:
            variable = program.variables[_transfer_key(route, item_id, sent)]
            units[item_id].add(variable, 1.0)
    for item_id in sorted(planning.terminal_values):
        split = Expression(
            terms={
                program.variables["terminal_cost", item_id]: 1.0,
                program.variables["terminal_salvage", item_id]: 1.0,
            }
        )
        program.add_equal(_combine((split, 1), (units[item_id], -1)), 0)


def _set_objective(program: Program, planning: PlanningInput) -> None:
    """Set the objective: the profit of the run when the solution is followed.

    It is the cash after interest at the close of the window, plus receivables at
    the end, plus stock at its salvage value, less the cash at the start of the run.
    The units at the end of an item with a terminal value count at its terminal
    value up to its expected use and at its salvage value above it.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    window_end = planning.window_end
    objective = _cash_after_interest(program, planning, window_end)
    objective.constant = -float(planning.starting_cash)
    for receivable in planning.state.receivables:
        if receivable.payment_period > window_end:
            objective.constant += float(receivable.amount)
    for order, warehouse_id, period in _ship_places(planning):
        if _payment_period(planning, order, period) > window_end:
            terms = planning.customers[order.customer].products[order.product]
            variable = program.variables[_ship_key(order, warehouse_id, period)]
            objective.add(variable, float(terms.price))
    for warehouse_id, warehouse in sorted(planning.warehouses.items()):
        for item_id in warehouse.accepts:
            if item_id in planning.terminal_values:
                continue
            stock = program.variables["stock", warehouse_id, item_id, window_end]
            objective.add(stock, float(planning.items[item_id].salvage_value))
    for item_id, terminal in sorted(planning.terminal_values.items()):
        at_cost = program.variables["terminal_cost", item_id]
        objective.add(at_cost, float(terminal.value))
        at_salvage = program.variables["terminal_salvage", item_id]
        objective.add(at_salvage, float(planning.items[item_id].salvage_value))
    program.objective = objective


def _costs_of(program: Program) -> np.ndarray:
    """Give the costs HiGHS minimizes: the objective without its constant, negated.

    Args:
        program (Program): The program.

    Returns:
        np.ndarray: The cost of every variable.
    """
    costs = np.zeros(len(program.upper_bounds))
    for variable, coefficient in program.objective.terms.items():
        costs[variable] = -coefficient
    return costs


def _solve(
    program: Program,
    fixed: Mapping[int, float] | None = None,
    time_limit: float | None = None,
) -> tuple[np.ndarray, float]:
    """Solve a program with HiGHS as a linear program.

    Binary variables take any value from 0 to 1, unless they are fixed.

    Args:
        program (Program): The program.
        fixed (Mapping[int, float] | None, optional): Values that variables keep, by
            index.
        time_limit (float | None, optional): Seconds the solve may take; None for no
            limit.

    Returns:
        tuple[np.ndarray, float]: The value of every variable and the value of the
            objective.

    Raises:
        TimeoutError: If HiGHS stops at the time limit.
        RuntimeError: If HiGHS ends with another status than optimal.
    """
    values, value, _ = _solve_with_diagnostics(program, fixed, time_limit)
    return values, value


def _solve_with_diagnostics(
    program: Program,
    fixed: Mapping[int, float] | None = None,
    time_limit: float | None = None,
    diagnostics: list[LinearSolve] | None = None,
) -> tuple[np.ndarray, float, LinearSolve]:
    """Solve a program with HiGHS as a linear program and report the solve.

    Binary variables take any value from 0 to 1, unless they are fixed.

    Args:
        program (Program): The program.
        fixed (Mapping[int, float] | None, optional): Values that variables keep, by
            index.
        time_limit (float | None, optional): Seconds the solve may take; None for no
            limit.
        diagnostics (list[LinearSolve] | None, optional): Receives the report of the
            solve, changed in place.

    Returns:
        tuple[np.ndarray, float, LinearSolve]: The value of every variable, the value
            of the objective and the report of the solve.

    Raises:
        TimeoutError: If HiGHS stops at the time limit.
        RuntimeError: If HiGHS ends with another status than optimal.
    """
    count = len(program.upper_bounds)
    costs = _costs_of(program)
    bounds = [
        (0.0, None if math.isinf(upper) else upper) for upper in program.upper_bounds
    ]
    for variable, value in (fixed or {}).items():
        bounds[variable] = (value, value)
    at_most, at_most_bounds = _matrix_of(program.at_most_rows, count)
    equal, equal_values = _matrix_of(program.equal_rows, count)
    options: dict[str, float] = {"primal_feasibility_tolerance": FEASIBILITY_TOLERANCE}
    if time_limit is not None:
        options["time_limit"] = time_limit
    # The stubs of scipy leave out the sparse matrices that linprog takes.
    solve_with_highs = cast(Callable[..., Any], linprog)
    started = time.perf_counter()
    result = solve_with_highs(
        costs,
        A_ub=at_most,
        b_ub=at_most_bounds,
        A_eq=equal,
        b_eq=equal_values,
        bounds=bounds,
        method="highs",
        options=options,
    )
    report = LinearSolve(
        status=int(result.status),
        objective=(
            -float(result.fun) + program.objective.constant
            if result.get("fun") is not None
            else None
        ),
        elapsed_seconds=time.perf_counter() - started,
        termination_reason=str(result.message),
        time_limit_seconds=time_limit,
    )
    if diagnostics is not None:
        diagnostics.append(report)
    if result.status == 1 and time_limit is not None:
        raise TimeoutError(str(result.message))
    if result.status != 0:
        raise RuntimeError(str(result.message))
    values = np.asarray(result.x, dtype=float)
    return values, -float(result.fun) + program.objective.constant, report


def solve_integer(
    program: Program,
    time_limit: float,
    period: int,
    diagnostics: list[IntegerSolve | LinearSolve] | None = None,
) -> tuple[np.ndarray | None, float | None, IntegerSolve]:
    """Solve a program with binary variables with HiGHS within its limits.

    HiGHS reads the objective without its constant, which changes the value of every
    solution alike. Each `milp` call stops at `NODE_LIMIT` nodes or when the bound
    exceeds the value of its solution by at most `GAP_LIMIT`, in the money of the
    program, with no relative gap. One budget of `time_limit` seconds, counted from the
    first call, covers every call. A solve that HiGHS calls infeasible, or unbounded or
    infeasible, runs once more without its presolve, which can find a program of very
    small numbers infeasible. The binaries found are then fixed and the linear program
    solved again, so that every row holds to `FEASIBILITY_TOLERANCE`. `milp` leaves
    `FIXED_RESERVE` of the budget to that linear program, which takes the seconds left.
    When it stops at its time limit, the solve keeps the solution of `milp` with its
    binaries rounded, the value of its report, and stops at the time limit.

    Args:
        program (Program): The program.
        time_limit (float): Seconds the whole solve may take.
        period (int): The first period of the window, named in an error.
        diagnostics (list[IntegerSolve | LinearSolve] | None, optional): Receives the
            report of every solve, changed in place.

    Returns:
        tuple[np.ndarray | None, float | None, IntegerSolve]: The value of every
            variable and the value of the objective, both None without a solution,
            and the report of the solve, whose value and bound count the constant.

    Raises:
        RuntimeError: If HiGHS ends the program infeasible or unbounded, naming the
            period.

    Examples:
        >>> program = Program()
        >>> program.add_binary(("order", "s", "chip", 1, False, "main"))
        0
        >>> program.objective = Expression(terms={0: 2.0}, constant=1.0)
        >>> values, value, report = solve_integer(program, 60.0, 1)
        >>> float(values[0]), value, report.value, report.gap
        (1.0, 3.0, 3.0, 0.0)
    """
    count = len(program.upper_bounds)
    costs = _costs_of(program)
    constraints: list[LinearConstraint] = []
    at_most, at_most_bounds = _matrix_of(program.at_most_rows, count)
    if at_most is not None and at_most_bounds is not None:
        constraints.append(LinearConstraint(at_most, -np.inf, at_most_bounds))
    equal, equal_values = _matrix_of(program.equal_rows, count)
    if equal is not None and equal_values is not None:
        constraints.append(LinearConstraint(equal, equal_values, equal_values))
    integrality = np.zeros(count)
    integrality[sorted(program.binaries)] = 1
    started = time.perf_counter()

    def seconds_left() -> float:
        return max(time_limit - (time.perf_counter() - started), 0.0)

    # The stubs of scipy leave out the sparse matrices that milp takes.
    solve_with_highs = cast(Callable[..., OptimizeResult], milp)
    bounds = Bounds(np.zeros(count), np.array(program.upper_bounds))
    limits = {"node_limit": NODE_LIMIT, "mip_rel_gap": 0.0, "mip_abs_gap": GAP_LIMIT}

    def solve_within(
        options: dict[str, float | bool],
    ) -> tuple[OptimizeResult, float]:
        # scipy passes `mip_abs_gap`, an option it does not name, to HiGHS as it is.
        call_started = time.perf_counter()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "Unrecognized options", RuntimeWarning)
            result = solve_with_highs(
                costs,
                constraints=constraints,
                integrality=integrality,
                bounds=bounds,
                options=limits | options,
            )
        return result, time.perf_counter() - call_started

    reserve = FIXED_RESERVE * time_limit
    result, milp_seconds = solve_within({"time_limit": time_limit - reserve})
    if result.status == 2 or is_unbounded_or_infeasible(result):
        if diagnostics is not None:
            diagnostics.append(
                IntegerSolve(
                    period=period,
                    solution_found=False,
                    stopped_at_time_limit=False,
                    gap=math.inf,
                    seconds=milp_seconds,
                    status=int(result.status),
                    termination_reason=(
                        str(result.get("message"))
                        if result.get("message") is not None
                        else None
                    ),
                    time_limit_seconds=time_limit,
                    node_limit=NODE_LIMIT,
                    relative_gap_limit=0.0,
                    absolute_gap_limit=GAP_LIMIT,
                )
            )
        retry_seconds = max(seconds_left() - reserve, 0.0)
        result, milp_seconds = solve_within(
            {"time_limit": retry_seconds, "presolve": False}
        )
    report = read_integer_solve(
        result,
        period,
        program.objective.constant,
        time_limit_seconds=time_limit,
    )
    report = replace(report, seconds=milp_seconds)
    if diagnostics is not None:
        diagnostics.append(report)
    if not report.solution_found:
        return None, None, replace(report, seconds=time.perf_counter() - started)
    chosen = {index: float(round(result.x[index])) for index in program.binaries}
    fixed_limit = seconds_left()
    fixed_started = time.perf_counter()
    fixed_diagnostics: list[LinearSolve] = []
    try:
        if diagnostics is None:
            values, value = _solve(program, chosen, fixed_limit)
            fixed_solve = LinearSolve(
                status=0,
                objective=value,
                elapsed_seconds=time.perf_counter() - fixed_started,
                termination_reason="optimal",
                time_limit_seconds=fixed_limit,
                kind="linear_fixed_binary",
            )
        else:
            values, value, fixed_solve = _solve_with_diagnostics(
                program,
                chosen,
                fixed_limit,
                diagnostics=fixed_diagnostics,
            )
            fixed_solve = replace(fixed_solve, kind="linear_fixed_binary")
        if diagnostics is not None:
            diagnostics.extend(
                replace(solve, kind="linear_fixed_binary")
                for solve in fixed_diagnostics
            )
        report = replace(report, fixed_binary_solve=fixed_solve)
    except TimeoutError as error:
        if diagnostics is None:
            fixed_solve = LinearSolve(
                status=1,
                objective=None,
                elapsed_seconds=time.perf_counter() - fixed_started,
                termination_reason=str(error),
                time_limit_seconds=fixed_limit,
                kind="linear_fixed_binary",
            )
        else:
            diagnostics.extend(
                replace(solve, kind="linear_fixed_binary")
                for solve in fixed_diagnostics
            )
            fixed_solve = replace(fixed_diagnostics[-1], kind="linear_fixed_binary")
        values = np.asarray(result.x, dtype=float)
        values[list(chosen)] = list(chosen.values())
        stopped = replace(
            report,
            stopped_at_time_limit=True,
            seconds=time.perf_counter() - started,
            fixed_binary_solve=fixed_solve,
        )
        return values, report.value, stopped
    except RuntimeError as error:
        if diagnostics is not None:
            diagnostics.extend(
                replace(solve, kind="linear_fixed_binary")
                for solve in fixed_diagnostics
            )
        raise RuntimeError(f"period {period}: {error}") from error
    return values, value, replace(report, seconds=time.perf_counter() - started)


def is_unbounded_or_infeasible(result: OptimizeResult) -> bool:
    """Tell whether a result of `milp` is unbounded or infeasible, HiGHS status 9.

    scipy gives status 4 to the node limit of HiGHS, whose message names HiGHS
    status 16, `Solution limit reached`, to a program HiGHS finds unbounded or
    infeasible, and to other ends, such as an interrupt. A status 4 without a
    solution `x` that is not the node limit counts as unbounded or infeasible.

    Args:
        result (OptimizeResult): The result of `scipy.optimize.milp`.

    Returns:
        bool: True when its status is 4, it has no `x` and its message does not name
            HiGHS status 16.

    Examples:
        >>> is_unbounded_or_infeasible(
        ...     OptimizeResult(
        ...         status=4,
        ...         x=None,
        ...         message="(HiGHS Status 9: model_status is Primal infeasible)",
        ...     )
        ... )
        True
    """
    return (
        result.status == 4
        and result.get("x") is None
        and "HiGHS Status 16" not in str(result.get("message", ""))
    )


def read_integer_solve(
    result: OptimizeResult,
    period: int,
    constant: float = 0.0,
    *,
    time_limit_seconds: float | None = None,
) -> IntegerSolve:
    """Read the report of a solve of `milp`.

    Status 1 is the time limit; status 4 is the node limit when its message names
    HiGHS status 16, `Solution limit reached`. A solve stopped at either may have no
    solution. A status 4 with a solution and another status of HiGHS, such as an
    interrupt or an unknown end, stopped at no limit.

    Args:
        result (OptimizeResult): The result of `scipy.optimize.milp`.
        period (int): The first period of the window solved.
        constant (float, optional): The constant of the objective, which HiGHS does
            not read.
        time_limit_seconds (float | None, optional): The time limit of the solve.

    Returns:
        IntegerSolve: Whether it found a solution, the limit it stopped at, if any,
            the value of its solution and the bound of its program, the constant
            counted, and their gap, the bound less the value and at least 0,
            `math.inf` without a solution.

    Raises:
        RuntimeError: If the result has no solution `x` and stopped at no limit,
            such as a status 4 that is unbounded or infeasible, naming the period.

    Examples:
        >>> result = OptimizeResult(
        ...     status=1, x=np.array([1.0]), fun=-3.0, mip_dual_bound=-4.0
        ... )
        >>> solve = read_integer_solve(result, 3)
        >>> solve.stopped_at_time_limit, solve.value, solve.bound, solve.gap
        (True, 3.0, 4.0, 1.0)
    """
    at_time_limit = result.status == 1
    at_node_limit = result.status == 4 and "HiGHS Status 16" in str(
        result.get("message", "")
    )
    found = result.get("x") is not None
    if not (found or at_time_limit or at_node_limit):
        raise RuntimeError(
            f"period {period}: the integer program has no solution, status "
            f"{result.status}"
        )
    if not found:
        return IntegerSolve(
            period=period,
            solution_found=False,
            stopped_at_time_limit=at_time_limit,
            stopped_at_node_limit=at_node_limit,
            gap=math.inf,
            status=int(result.status),
            termination_reason=(
                str(result.get("message"))
                if result.get("message") is not None
                else None
            ),
            time_limit_seconds=time_limit_seconds,
            node_limit=NODE_LIMIT,
            relative_gap_limit=0.0,
            absolute_gap_limit=GAP_LIMIT,
        )
    # HiGHS minimizes the costs, the objective with a minus sign. Its bound can lie a
    # rounding of floating point below the value of its solution; the gap is then 0.
    return IntegerSolve(
        period=period,
        stopped_at_time_limit=at_time_limit,
        stopped_at_node_limit=at_node_limit,
        gap=max(float(result.fun) - float(result.mip_dual_bound), 0.0),
        value=constant - float(result.fun),
        bound=constant - float(result.mip_dual_bound),
        status=int(result.status),
        termination_reason=(
            str(result.get("message")) if result.get("message") is not None else None
        ),
        time_limit_seconds=time_limit_seconds,
        node_limit=NODE_LIMIT,
        relative_gap_limit=0.0,
        absolute_gap_limit=GAP_LIMIT,
    )


def _matrix_of(
    rows: list[tuple[dict[int, float], float]], count: int
) -> tuple[coo_array | None, np.ndarray | None]:
    """Give the sparse matrix and the right sides of rows, or None without rows.

    Args:
        rows (list[tuple[dict[int, float], float]]): The terms and right side of
            every row.
        count (int): The number of variables.

    Returns:
        tuple[coo_array | None, np.ndarray | None]: The matrix and the right sides.
    """
    if not rows:
        return None, None
    row_indexes: list[int] = []
    column_indexes: list[int] = []
    coefficients: list[float] = []
    for row, (terms, _) in enumerate(rows):
        for variable, coefficient in terms.items():
            row_indexes.append(row)
            column_indexes.append(variable)
            coefficients.append(coefficient)
    matrix = coo_array(
        (coefficients, (row_indexes, column_indexes)), shape=(len(rows), count)
    )
    return matrix, np.array([side for _, side in rows])


def _solution_of(
    program: Program, planning: PlanningInput, values: np.ndarray, value: float
) -> Solution:
    """Give the solution of a solved program: its value and its first period.

    Args:
        program (Program): The program.
        planning (PlanningInput): The planning input.
        values (np.ndarray): The value of every variable.
        value (float): The value of the objective.

    Returns:
        Solution: The solution, without values at most `NOISE`.
    """
    first = planning.first_period

    def solved(key: Key) -> float:
        return float(values[program.variables[key]])

    ships = [
        SolutionShip(
            order=order.id,
            warehouse=warehouse_id,
            quantity=solved(_ship_key(order, warehouse_id, period)),
        )
        for order, warehouse_id, period in _ship_places(planning)
        if period == first
    ]
    transfers = [
        SolutionTransfer(
            item=item_id,
            source=route.source,
            destination=route.destination,
            quantity=solved(_transfer_key(route, item_id, period)),
        )
        for route, item_id, period in _transfer_places(planning)
        if period == first
    ]
    repairs = [
        SolutionRepair(line=line_id, amount=solved(("repair", line_id, first)))
        for line_id in sorted(planning.lines)
    ]
    produces = [
        SolutionProduce(
            line=line_id,
            item=item_id,
            recipe=recipe,
            overtime=overtime,
            quantity=solved(("make", line_id, item_id, recipe, overtime, period)),
        )
        for line_id, item_id, recipe, overtime, period in _make_places(planning)
        if period == first
    ]
    buys = [
        SolutionBuy(
            supplier=option.supplier,
            material=option.material,
            warehouse=warehouse_id,
            express=option.express,
            quantity=solved(_buy_key(option, warehouse_id)),
        )
        for option, warehouse_id in _buy_places(planning)
        if option.period == first
    ]
    set_at_close = {
        line_id: item_id
        for line_id in changeover_lines(planning)
        for item_id in sorted(planning.lines[line_id].items)
        if solved(("set", line_id, item_id, first)) > 0.5
    }
    return Solution(
        value=value,
        ships=tuple(ship for ship in ships if ship.quantity > NOISE),
        transfers=tuple(
            transfer for transfer in transfers if transfer.quantity > NOISE
        ),
        repairs=tuple(repair for repair in repairs if repair.amount > NOISE),
        produces=tuple(produce for produce in produces if produce.quantity > NOISE),
        buys=tuple(buy for buy in buys if buy.quantity > NOISE),
        set_at_close=set_at_close,
    )


def _good_roundings(
    planning: PlanningInput,
) -> Iterator[tuple[str, str, str, bool, int]]:
    """Give every production whose good units the engine can round.

    The good share is above 0 and below 1, and the production is ready within the
    window.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[str, str, str, bool, int]: The line, the item, the recipe, whether in
            overtime, and the period, as `_make_places` gives them.
    """
    for make in _make_places(planning):
        line_id, item_id, _, _, period = make
        line_item = planning.lines[line_id].items[item_id]
        share = line_item.good_shares[period]
        ready = period + line_item.lead_time - 1
        if 0 < share < 1 and ready <= planning.window_end:
            yield make


def _input_roundings(
    planning: PlanningInput,
) -> Iterator[tuple[tuple[str, str, str, bool, int], str]]:
    """Give every input of a production that the engine can round up.

    The recipe quantity is not a whole number.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[tuple[str, str, str, bool, int], str]: The production, as
            `_make_places` gives it, and the input.
    """
    for make in _make_places(planning):
        _, item_id, recipe, _, _ = make
        for input_id, quantity in sorted(
            planning.items[item_id].recipes[recipe].items()
        ):
            if quantity != quantity.to_integral_value():
                yield make, input_id


def _accepted_roundings(
    planning: PlanningInput,
) -> Iterator[tuple[BuyOption, str, Arrival]]:
    """Give every arrival of a buy whose accepted units the engine can round.

    The accepted share is above 0 and below 1, and the arrival is within the
    window.

    Args:
        planning (PlanningInput): The planning input.

    Yields:
        tuple[BuyOption, str, Arrival]: The option, the warehouse and the arrival.
    """
    for option, warehouse_id in _buy_places(planning):
        for arrival in _within_window(planning, option.arrivals):
            if 0 < arrival.accepted < 1:
                yield option, warehouse_id, arrival


def _add_rounding_variables(program: Program, planning: PlanningInput) -> None:
    """Add the units the engine may round in favor of the factory, for `solve_relaxed`.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    for make in _good_roundings(planning):
        program.add_variable(("good_more", *make), GOOD_ROUNDING)
        program.add_variable(("good_less", *make), GOOD_ROUNDING)
    for make, input_id in _input_roundings(planning):
        program.add_variable(("input_rounding", *make, input_id), INPUT_ROUNDING)
    for option, warehouse_id, arrival in _accepted_roundings(planning):
        key = (*_buy_key(option, warehouse_id)[1:], arrival.period)
        program.add_variable(("accepted_more", *key), ACCEPTED_ROUNDING)
        program.add_variable(("accepted_less", *key), ACCEPTED_ROUNDING)


def _add_rounding_rows(program: Program, planning: PlanningInput) -> None:
    """Add the rows that keep each rounding within what a decision of 0.001 allows.

    A rounding is at most half the units started for more good units, the good units
    for fewer, the units started for an input, and 1.5 times the units ordered for
    accepted units, so a decision of 0 rounds nothing.

    Args:
        program (Program): The program, changed in place.
        planning (PlanningInput): The planning input.
    """
    if not program.rounding:
        return
    for make in _good_roundings(planning):
        started = program.variables["make", *make]
        more = program.variables["good_more", *make]
        program.add_at_most(Expression(terms={more: 1.0, started: -0.5}), 0)
        line_id, item_id, _, _, period = make
        share = planning.lines[line_id].items[item_id].good_shares[period]
        less = program.variables["good_less", *make]
        program.add_at_most(Expression(terms={less: 1.0, started: -float(share)}), 0)
    for make, input_id in _input_roundings(planning):
        rounding = program.variables["input_rounding", *make, input_id]
        started = program.variables["make", *make]
        program.add_at_most(Expression(terms={rounding: 1.0, started: -1.0}), 0)
    for option, warehouse_id, arrival in _accepted_roundings(planning):
        key = (*_buy_key(option, warehouse_id)[1:], arrival.period)
        ordered = program.variables[_buy_key(option, warehouse_id)]
        for kind in ("accepted_more", "accepted_less"):
            rounding = program.variables[kind, *key]
            program.add_at_most(Expression(terms={rounding: 1.0, ordered: -1.5}), 0)
