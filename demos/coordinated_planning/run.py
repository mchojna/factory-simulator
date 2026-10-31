"""The coordinated planning demo command: planner, procurement and reviewer model roles.

Examples:
    >>> DEMO_NAME
    'coordinated-planning'
"""

from demos.coordinated_planning import DEMO_NAME, STRATEGY
from demos.utils.model import run_model_command


def main() -> None:
    """Run a bounded live model against the simulator.

    Examples:
        >>> STRATEGY in {"single_prompt", "tools_memory", "coordinated"}
        True
    """
    run_model_command(DEMO_NAME, STRATEGY)


if __name__ == "__main__":
    main()
