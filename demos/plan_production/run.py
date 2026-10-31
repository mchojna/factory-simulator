"""The plan production demo command: the myopic optimizer plans every period.

Examples:
    >>> demo_parser(DEMO_NAME).parse_args([]).seed
    7
"""

from dataclasses import asdict

import httpx2 as httpx

from demos.plan_production import DEMO_NAME
from demos.utils.cli import demo_parser, save_finished_run
from demos.utils.client import start_demo_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.optimizers.myopic import myopic_optimizer


def main() -> None:
    """Play the small factory with the myopic optimizer.

    Examples:
        >>> demo_parser(DEMO_NAME).parse_args([]).seed
        7
    """
    arguments = demo_parser(DEMO_NAME).parse_args()
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        run = start_demo_run(client, arguments.seed)

        def check(period: int, decisions: list[JsonObject]) -> list[JsonObject]:
            return benchmark.create_check(client, str(run["id"]), period, decisions)

        optimizer = myopic_optimizer(check, time_limit=2.0)
        result = benchmark.play_run(client, run, optimizer)
        trace = [
            {
                "period": period.period,
                "proposed": period.proposed,
                "decisions": period.decisions,
                "checks": period.checks,
                "dropped": period.dropped,
                "fitted": period.fitted,
                "solves": [asdict(solve) for solve in period.solves],
                "error_type": period.error_type,
                "error_message": period.error_message,
            }
            for period in optimizer.periods
        ]
        summary = save_finished_run(
            client,
            DEMO_NAME,
            run,
            result,
            arguments.output,
            {"optimizer": "myopic", "periods": trace},
        )
    print(summary)


if __name__ == "__main__":
    main()
