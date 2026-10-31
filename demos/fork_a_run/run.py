"""The fork a run demo command: fork a finished run and finish the fork.

Examples:
    >>> demo_parser(DEMO_NAME).parse_args([]).seed
    7
"""

import httpx2 as httpx

from demos.fork_a_run import DEMO_NAME
from demos.utils.cli import demo_parser, save_finished_run
from demos.utils.client import start_demo_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions

FORK_PERIOD = 2


def main() -> None:
    """Finish a parent run and fork it at the start of period 2.

    Examples:
        >>> FORK_PERIOD
        2
    """
    arguments = demo_parser(DEMO_NAME).parse_args()
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        parent = start_demo_run(client, arguments.seed)
        parent_result = benchmark.play_run(client, parent, no_decisions)
        parent_summary = save_finished_run(
            client,
            DEMO_NAME,
            parent,
            parent_result,
            arguments.output,
            {"role": "parent"},
        )
        fork = benchmark.send(
            client,
            "POST",
            f"/runs/{parent['id']}/forks",
            {"period": FORK_PERIOD},
        )
        fork_result = benchmark.play_run(client, fork, no_decisions)
        summary = save_finished_run(
            client,
            DEMO_NAME,
            fork,
            fork_result,
            arguments.output,
            {
                "role": "fork",
                "forked_from": parent["id"],
                "forked_from_period": FORK_PERIOD,
                "parent_summary": str(parent_summary),
            },
        )
    print(summary)


if __name__ == "__main__":
    main()
