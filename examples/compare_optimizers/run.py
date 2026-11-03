"""The optimizer comparison command: profits of the runs of a model example.

Examples:
    >>> EXAMPLE_NAME
    'compare-optimizers'
"""

from examples.compare_optimizers import EXAMPLE_NAME
from examples.utils.cli import example_parser
from examples.utils.model import compare_runs


def main() -> None:
    """Read one example summary and compare its completed runs.

    Examples:
        >>> EXAMPLE_NAME
        'compare-optimizers'
    """
    arguments = example_parser(EXAMPLE_NAME, accepts_summary=True).parse_args()
    print(compare_runs(arguments.summary, arguments.output))


if __name__ == "__main__":
    main()
