from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Context, Decimal, getcontext, localcontext
from typing import Any

import pytest
from factories import tiny_manifest, tiny_scenario, to_engine
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.engine import (
    InputError,
    check_factory,
    in_decimal_context,
)


# A board of one chip worth 0.5000 at a cost of 0.7346 on the line: the bound of its
# salvage value is 1.000 * 0.5000 + 0.7346 = 1.2346.
def board_salvage_of(salvage_value: str) -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["materials"]["chip"]["salvage_value"] = "0.5000"
    board = manifest["components"]["board"]
    board["recipes"] = {"standard": {"chip": "1.000"}}
    board["salvage_value"] = salvage_value
    manifest["lines"]["line-1"]["items"]["board"]["cost"] = "0.7346"
    return manifest


def run_in_new_thread[R](function: Callable[[], R]) -> R:
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(function).result()


@in_decimal_context
def precision() -> int:
    return getcontext().prec


@in_decimal_context
def grow_and_root(rate: Decimal, periods: int) -> tuple[Decimal, Decimal]:
    grown = (1 + rate) ** periods
    return grown, grown.sqrt()


def test_a_salvage_bound_is_summed_exactly_inside_a_coarse_context():
    factory, _ = to_engine(board_salvage_of("1.2346"), tiny_scenario())

    # With 3 digits the bound would be summed to 1.23 and refuse 1.2346.
    with localcontext(Context(prec=3)):
        check_factory(factory)


def test_a_salvage_value_just_above_its_bound_is_refused():
    factory, _ = to_engine(board_salvage_of("1.2347"), tiny_scenario())

    with localcontext(Context(prec=3)), pytest.raises(InputError) as refusal:
        check_factory(factory)

    assert str(refusal.value) == (
        "components.board.salvage_value: is above the value of its inputs and the "
        "cost of making it"
    )


def test_engine_context_has_precision_50_in_a_new_thread():
    assert run_in_new_thread(precision) == 50


@pytest.mark.property
@given(
    st.decimals(min_value=0, max_value=1, places=4),
    st.integers(min_value=0, max_value=100),
)
def test_calculation_in_a_new_thread_equals_the_main_thread(
    rate: Decimal, periods: int
):
    with localcontext(prec=10):
        in_main_thread = grow_and_root(rate, periods)
    in_new_thread = run_in_new_thread(lambda: grow_and_root(rate, periods))
    assert in_new_thread == in_main_thread
    assert [value.as_tuple() for value in in_new_thread] == [
        value.as_tuple() for value in in_main_thread
    ]
