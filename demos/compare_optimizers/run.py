"""The compare optimizers demo command: compare the profits of the runs of a model demo.

Examples:
    >>> DEMO_NAME
    'compare-optimizers'
"""

from demos.compare_optimizers import DEMO_NAME
from demos.utils.cli import demo_parser
from demos.utils.model import compare_runs


def main() -> None:
    """Read one demo summary and compare its completed runs.

    Examples:
        >>> DEMO_NAME
        'compare-optimizers'
    """
    arguments = demo_parser(DEMO_NAME, accepts_summary=True).parse_args()
    print(compare_runs(arguments.summary, arguments.output))


if __name__ == "__main__":
    main()
