import re

import pytest
from factories import example_count
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.api.services.runs.stored import create_run_id


def test_a_run_id_is_32_hexadecimal_digits():
    run_id = create_run_id()

    assert len(run_id) == 32
    assert set(run_id) <= set("0123456789abcdef")


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(st.integers(min_value=2, max_value=200))
def test_run_ids_created_many_times_are_all_different_and_32_hexadecimal_digits(
    count: int,
):
    run_ids = [create_run_id() for _ in range(count)]

    assert len(set(run_ids)) == count
    assert all(re.fullmatch("[0-9a-f]{32}", run_id) for run_id in run_ids)
