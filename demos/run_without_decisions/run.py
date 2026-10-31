"""The run without decisions demo command: play a run with empty decisions.

Examples:
    >>> demo_parser(DEMO_NAME).parse_args([]).seed
    7
"""

import httpx2 as httpx

from demos.run_without_decisions import DEMO_NAME
from demos.utils.cli import demo_parser, save_finished_run
from demos.utils.client import start_demo_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


def main() -> None:
    """Play a three-period run with no submitted decisions.

    Examples:
        >>> demo_parser(DEMO_NAME).parse_args([]).seed
        7
    """
    arguments = demo_parser(DEMO_NAME).parse_args()
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        run = start_demo_run(client, arguments.seed)
        result = benchmark.play_run(client, run, no_decisions)
        summary = save_finished_run(client, DEMO_NAME, run, result, arguments.output)
    print(summary)


if __name__ == "__main__":
    main()
