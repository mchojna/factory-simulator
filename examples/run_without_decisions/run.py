"""The run without decisions example command: play a run with empty decisions.

Examples:
    >>> example_parser(EXAMPLE_NAME).parse_args([]).seed
    7
"""

import httpx2 as httpx

from examples.run_without_decisions import EXAMPLE_NAME
from examples.utils.cli import example_parser, save_finished_run
from examples.utils.client import start_example_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


def main() -> None:
    """Play a three-period run with no submitted decisions.

    Examples:
        >>> example_parser(EXAMPLE_NAME).parse_args([]).seed
        7
    """
    arguments = example_parser(EXAMPLE_NAME).parse_args()
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        run = start_example_run(client, arguments.seed)
        result = benchmark.play_run(client, run, no_decisions)
        summary = save_finished_run(client, EXAMPLE_NAME, run, result, arguments.output)
    print(summary)


if __name__ == "__main__":
    main()
