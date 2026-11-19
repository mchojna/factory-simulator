import os

import pytest

from factory_simulator.benchmark.program.solve import TIME_LIMIT

pytest_plugins = ["pytester"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--stress-seeds",
        type=int,
        default=20,
        help="the number of seeds of the stress test, from 0; 20 by default",
    )
    parser.addoption(
        "--stress-scenarios",
        default="all",
        help=(
            "the scenarios of the stress test, names separated by commas; "
            "all by default"
        ),
    )
    parser.addoption(
        "--stress-workers",
        type=int,
        default=os.cpu_count(),
        help="the processes that play worlds; the number of CPUs by default",
    )
    parser.addoption(
        "--stress-time-limit",
        type=float,
        default=TIME_LIMIT,
        help=f"the seconds every solve may take; {TIME_LIMIT} by default",
    )
    parser.addoption(
        "--stress-evaluation",
        action="store_true",
        help=(
            "the evaluation seeds 1000 to 1019 of the confirmatory evaluation; "
            "off by default"
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    # A marker expression on the command line replaces the one of addopts, so this hook
    # removes the stress test from every run whose expression does not name it.
    if "stress" in config.option.markexpr:
        return
    stress = [item for item in items if item.get_closest_marker("stress")]
    if stress:
        config.hook.pytest_deselected(items=stress)
        items[:] = [item for item in items if item not in stress]
