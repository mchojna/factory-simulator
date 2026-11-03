"""The single-prompt planning example command: one model prompt plans each period.

Examples:
    >>> EXAMPLE_NAME
    'single-prompt-planning'
"""

from examples.single_prompt_planning import EXAMPLE_NAME, STRATEGY
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
