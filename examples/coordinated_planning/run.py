"""The coordinated planning example: planner, procurement and reviewer model roles.

Examples:
    >>> EXAMPLE_NAME
    'coordinated-planning'
"""

from examples.coordinated_planning import EXAMPLE_NAME, STRATEGY
from examples.utils.model import run_model_command


def main() -> None:
    """Run a bounded live model against the simulator.

    Examples:
        >>> STRATEGY in {"single_prompt", "tools_memory", "coordinated"}
        True
    """
    run_model_command(EXAMPLE_NAME, STRATEGY)


if __name__ == "__main__":
    main()
