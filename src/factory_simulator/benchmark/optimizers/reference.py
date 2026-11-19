"""The reference optimizer: the profit program with the whole world of a run.

Examples:
    >>> optimizer = reference_optimizer(lambda period, decisions: [], [], {})
    >>> optimizer.relaxed_program_value is None
    True
"""

from factory_simulator.benchmark.client import Check, JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.solve import TIME_LIMIT
from factory_simulator.benchmark.program.world_source import planning_input_of


def reference_optimizer(
    check: Check,
    customer_orders: list[JsonObject],
    world: JsonObject,
    time_limit: float = TIME_LIMIT,
    exact: bool = False,
) -> Optimizer:
    """Give the reference optimizer of one run, which plans with the whole world.

    Every period it plans from the period to the horizon. When the program has a buy
    option in its first period, or a buy option with a minimum quantity above 0 or
    discount tiers, or a line item with a changeover time or cost above 0, it solves
    a mixed-integer program; otherwise a linear program. Its yes-or-no choices are
    binary in the first period of the program only. With `exact` it is the exact
    control: its choices are binary in every period, for a small world only.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period of the run it
            plays.
        customer_orders (list[dict[str, Any]]): Every customer order of that run.
        world (dict[str, Any]): The world of a finished run of no decisions of the same
            scenario and seed.
        time_limit (float, optional): Seconds every solve of a period may take.
        exact (bool, optional): Whether every choice of its program is binary in
            every period; a program of more than `EXACT_BINARY_LIMIT` binary
            variables then raises `ValueError`.

    Returns:
        Optimizer: A new optimizer whose planning source is `planning_input_of`.

    Examples:
        >>> reference_optimizer(lambda period, decisions: [], [], {}).solves
        []
    """

    def planning_source(
        description: JsonObject, observation: JsonObject
    ) -> PlanningInput:
        return planning_input_of(observation, customer_orders, world, description)

    return Optimizer(
        planning_source=planning_source,
        check=check,
        time_limit=time_limit,
        exact=exact,
    )


def customer_orders_of(periods: list[JsonObject]) -> list[JsonObject]:
    """Give every customer order seen in the observations of the periods of a run.

    Customer orders do not depend on decisions, so a run of no decisions shows every
    order of its world.

    Args:
        periods (list[dict[str, Any]]): The periods of `GET /runs/{id}/periods`.

    Returns:
        list[dict[str, Any]]: Every order once, as first seen.

    Examples:
        >>> order = {"id": "order-1-1"}
        >>> step = {
        ...     "step": "build_observation",
        ...     "observation": {"customer_orders": [order]},
        ... }
        >>> customer_orders_of([{"steps": [step]}, {"steps": [step]}])
        [{'id': 'order-1-1'}]
    """
    orders: dict[str, JsonObject] = {}
    for period in periods:
        for step in period["steps"]:
            if step["step"] == "build_observation":
                for order in step["observation"]["customer_orders"]:
                    orders.setdefault(order["id"], order)
    return list(orders.values())
