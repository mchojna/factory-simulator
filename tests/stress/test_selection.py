from pathlib import Path

import pytest

CONFTEST = Path(__file__).parents[1] / "conftest.py"

STRESS_TEST = """
import pytest


@pytest.mark.stress
def test_marked_stress():
    pass


def test_not_marked():
    pass
"""


@pytest.mark.parametrize(
    ("marker_expression", "passed"),
    [
        ("not property and not slow", 1),
        ("not slow", 1),
        ("stress", 1),
        ("stress or not stress", 2),
    ],
)
def test_a_stress_test_runs_only_when_the_marker_expression_names_stress(
    pytester: pytest.Pytester, marker_expression: str, passed: int
):
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(STRESS_TEST)

    result = pytester.runpytest_inprocess(
        "-p", "no:xdist", "-p", "no:cacheprovider", "-m", marker_expression
    )

    result.assert_outcomes(passed=passed)
