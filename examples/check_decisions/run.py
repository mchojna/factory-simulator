"""The check decisions example command: check a shipment before submitting it.

Examples:
    >>> example_parser(EXAMPLE_NAME).parse_args([]).seed
    7
"""

import httpx2 as httpx

from examples.check_decisions import EXAMPLE_NAME
from examples.utils.cli import example_parser, save_finished_run
from examples.utils.client import scenario_with_product_stock, start_example_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


def main() -> None:
    """Check a shipment, submit it and finish the remaining periods.

    Examples:
        >>> example_parser(EXAMPLE_NAME).parse_args([]).seed
        7
    """
    arguments = example_parser(EXAMPLE_NAME).parse_args()
    scenario = scenario_with_product_stock("4.000")
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        run = start_example_run(client, arguments.seed, scenario)
        run_id = str(run["id"])
        observation = benchmark.read(client, f"/runs/{run_id}/observation")
        decisions = [
            {
                "kind": "ship",
                "order": order["id"],
                "quantity": order["quantity"],
            }
            for order in observation["customer_orders"]
        ]
        outcomes = benchmark.create_check(
            client, run_id, int(observation["period"]), decisions
        )
        benchmark.send(
            client,
            "POST",
            f"/runs/{run_id}/decisions",
            {"period": observation["period"], "decisions": decisions},
        )
        result = benchmark.play_run(client, run, no_decisions)
        summary = save_finished_run(
            client,
            EXAMPLE_NAME,
            run,
            result,
            arguments.output,
            {"checked_decisions": decisions, "check_outcomes": outcomes},
        )
    print(summary)


if __name__ == "__main__":
    main()
