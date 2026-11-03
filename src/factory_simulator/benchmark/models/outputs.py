"""The outputs of the profit program: the solution of a window and its solves.

Examples:
    >>> SolutionRepair(line="line-1", amount=0.1).amount
    0.1
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, kw_only=True)
class SolutionShip:
    """A shipment of the first period of a solution.

    Attributes:
        order (str): Identifier of the customer order.
        warehouse (str): Identifier of the warehouse it leaves.
        quantity (float): Units shipped.

    Examples:
        >>> SolutionShip(order="order-1-1", warehouse="main", quantity=4.0).quantity
        4.0
    """

    order: str
    warehouse: str
    quantity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SolutionTransfer:
    """A transfer of the first period of a solution.

    Attributes:
        item (str): Identifier of the item.
        source (str): Identifier of the warehouse it leaves.
        destination (str): Identifier of the warehouse it goes to.
        quantity (float): Units transferred.

    Examples:
        >>> SolutionTransfer(
        ...     item="monitor", source="main", destination="centre", quantity=2.0
        ... ).destination
        'centre'
    """

    item: str
    source: str
    destination: str
    quantity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SolutionRepair:
    """A repair of the first period of a solution.

    Attributes:
        line (str): Identifier of the line.
        amount (float): Condition restored.

    Examples:
        >>> SolutionRepair(line="line-1", amount=0.1).line
        'line-1'
    """

    line: str
    amount: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SolutionProduce:
    """A production of the first period of a solution.

    Attributes:
        line (str): Identifier of the line.
        item (str): Identifier of the item made.
        recipe (str): Name of the recipe.
        overtime (bool): Whether it runs in overtime hours.
        quantity (float): Units started.

    Examples:
        >>> SolutionProduce(
        ...     line="line-1",
        ...     item="board",
        ...     recipe="standard",
        ...     overtime=False,
        ...     quantity=8.0,
        ... ).item
        'board'
    """

    line: str
    item: str
    recipe: str
    overtime: bool
    quantity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SolutionBuy:
    """A buy of the first period of a solution.

    Attributes:
        supplier (str): Identifier of the supplier.
        material (str): Identifier of the material.
        warehouse (str): Identifier of the warehouse it goes to.
        express (bool): Whether it is an express order.
        quantity (float): Units ordered.

    Examples:
        >>> SolutionBuy(
        ...     supplier="chip-maker",
        ...     material="chip",
        ...     warehouse="main",
        ...     express=False,
        ...     quantity=50.0,
        ... ).material
        'chip'
    """

    supplier: str
    material: str
    warehouse: str
    express: bool
    quantity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class LinearSolve:
    """One solve of a linear program and what HiGHS reports of it.

    Attributes:
        status (int): The status code of HiGHS.
        objective (float | None): The value of the program; None without a solution.
        elapsed_seconds (float): The time the solve took, in seconds.
        termination_reason (str): The termination message of HiGHS.
        time_limit_seconds (float | None, optional): The time limit of the solve; None
            without one.
        kind (str, optional): `linear`, `linear_relaxed` or `linear_fixed_binary`.

    Examples:
        >>> LinearSolve(
        ...     status=0, objective=8, elapsed_seconds=0.2, termination_reason="optimal"
        ... ).status
        0
    """

    status: int
    objective: float | None
    elapsed_seconds: float
    termination_reason: str
    time_limit_seconds: float | None = None
    kind: str = "linear"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegerSolve:
    """What a solve of an integer program reports.

    Attributes:
        period (int): The first period of the window solved.
        stopped_at_time_limit (bool): Whether HiGHS stopped at the time limit.
        gap (float): The bound less the value, in money: the most by which its
            solution can be below the best solution of its program; `math.inf`
            without a solution.
        value (float | None, optional): The value of its solution in its program,
            in money; None without a solution.
        bound (float | None, optional): The bound HiGHS proved on the value of every
            solution of its program, in money; None without a solution.
        solution_found (bool, optional): Whether the solve found a solution.
        stopped_at_node_limit (bool, optional): Whether HiGHS stopped at
            `NODE_LIMIT` nodes.
        seconds (float, optional): The time the solve took.
        status (int | None, optional): The status code of HiGHS; None without one.
        termination_reason (str | None, optional): The termination message of HiGHS;
            None without one.
        time_limit_seconds (float | None, optional): The time limit of the solve; None
            without one.
        node_limit (int | None, optional): The node limit of the solve; None without
            one.
        relative_gap_limit (float | None, optional): The relative gap limit of the
            solve; None without one.
        absolute_gap_limit (float | None, optional): The absolute gap limit of the
            solve; None without one.
        fixed_binary_solve (LinearSolve | None, optional): The solve of the linear
            program with the chosen binary variables fixed; None without one.
        changeovers (Mapping[str, int], optional): The changeovers of every
            changeover line in the first period of the window, in the order the
            decisions are submitted.
        planned_changeovers (Mapping[str, int], optional): The changeovers of every
            changeover line in the first period of the window in the changeover
            order, the changeovers the program counts.

    Examples:
        >>> IntegerSolve(period=7, stopped_at_time_limit=True, gap=0.05).solution_found
        True
    """

    period: int
    stopped_at_time_limit: bool
    gap: float
    value: float | None = None
    bound: float | None = None
    solution_found: bool = True
    stopped_at_node_limit: bool = False
    seconds: float = 0.0
    status: int | None = None
    termination_reason: str | None = None
    time_limit_seconds: float | None = None
    node_limit: int | None = None
    relative_gap_limit: float | None = None
    absolute_gap_limit: float | None = None
    fixed_binary_solve: LinearSolve | None = None
    changeovers: Mapping[str, int] = field(default_factory=dict[str, int])
    planned_changeovers: Mapping[str, int] = field(default_factory=dict[str, int])


@dataclass(frozen=True, slots=True, kw_only=True)
class Solution:
    """The value of the program and the decisions of the first period of its window.

    Attributes:
        value (float | None): The profit of the run when the solution is followed;
            None without a solution.
        ships (tuple[SolutionShip, ...]): The shipments.
        transfers (tuple[SolutionTransfer, ...]): The transfers.
        repairs (tuple[SolutionRepair, ...]): The repairs.
        produces (tuple[SolutionProduce, ...]): The productions, in the order of the
            program.
        buys (tuple[SolutionBuy, ...]): The buys.
        set_at_close (Mapping[str, str], optional): The item each changeover line is
            set for at the close of the first period, by line; a line set for none
            is left out.
        integer_solve (IntegerSolve | None, optional): The report of the solve of an
            integer program; None for a linear one.
        linear_solve (LinearSolve | None, optional): The report of the solve of a
            linear program; None for an integer one.

    Examples:
        >>> Solution(
        ...     value=1.5, ships=(), transfers=(), repairs=(), produces=(), buys=()
        ... ).integer_solve is None
        True
    """

    value: float | None
    ships: tuple[SolutionShip, ...]
    transfers: tuple[SolutionTransfer, ...]
    repairs: tuple[SolutionRepair, ...]
    produces: tuple[SolutionProduce, ...]
    buys: tuple[SolutionBuy, ...]
    set_at_close: Mapping[str, str] = field(default_factory=dict[str, str])
    integer_solve: IntegerSolve | None = None
    linear_solve: LinearSolve | None = None
