"""The single-prompt planning demo command: one model prompt plans each period.

Examples:
    >>> DEMO_NAME
    'single-prompt-planning'
"""

from demos.single_prompt_planning import DEMO_NAME, STRATEGY
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
