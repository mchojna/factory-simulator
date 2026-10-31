"""The tool-guided planning demo command: a model reads fields and checks plans.

Examples:
    >>> DEMO_NAME
    'tool-guided-planning'
"""

from demos.tool_guided_planning import DEMO_NAME, STRATEGY
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
