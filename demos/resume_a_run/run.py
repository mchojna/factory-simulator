"""The resume a run demo command: stop a run after period 1 and finish it later.

Examples:
    >>> demo_parser(DEMO_NAME, accepts_run_id=True).parse_args([]).run_id is None
    True
"""

import httpx2 as httpx

from demos.resume_a_run import DEMO_NAME
from demos.utils.cli import demo_parser, save_checkpoint, save_finished_run
from demos.utils.client import start_demo_run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions


def main() -> None:
    """Start a partial run or continue it by its HTTP run identifier.

    Raises:
        ValueError: If the run identifier names a finished run.

    Examples:
        >>> demo_parser(DEMO_NAME, accepts_run_id=True).parse_args([]).run_id is None
        True
    """
    arguments = demo_parser(DEMO_NAME, accepts_run_id=True).parse_args()
    with httpx.Client(base_url=arguments.server, timeout=30) as client:
        if arguments.run_id is None:
            run = start_demo_run(client, arguments.seed)
            first_observation = benchmark.read(client, f"/runs/{run['id']}/observation")
            observation = benchmark.send(
                client,
                "POST",
                f"/runs/{run['id']}/decisions",
                {"period": first_observation["period"], "decisions": []},
            )
            checkpoint = save_checkpoint(
                DEMO_NAME, run, arguments.seed, observation, arguments.output
            )
            print(checkpoint)
            return

        run = benchmark.read(client, f"/runs/{arguments.run_id}")
        if run["finished"]:
            raise ValueError(f"run {arguments.run_id} is already finished")
        result = benchmark.play_run(client, run, no_decisions)
        summary = save_finished_run(
            client,
            DEMO_NAME,
            run,
            result,
            arguments.output,
            {"resumed": True},
        )
    print(summary)


if __name__ == "__main__":
    main()
