from decimal import Decimal
from typing import Any, cast

import pytest
from factories import example_count, tiny_manifest, tiny_scenario
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import (
    Periods,
    Quantity,
    Seed,
    read_json_bytes,
    read_number,
    validate,
)
from factory_simulator.api.schemas.run import DecisionsCreate
from factory_simulator.engine import InputError

quantity = TypeAdapter[Decimal](Quantity)


periods = TypeAdapter[int](Periods)


seed = TypeAdapter[int](Seed)


def test_quantity_pads_text_to_3_places():
    assert quantity.validate_python("40").as_tuple() == Decimal("40.000").as_tuple()
    assert quantity.validate_python("40.5").as_tuple() == Decimal("40.500").as_tuple()


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        *(
            (text, "is not a plain decimal number")
            for text in [
                "NaN",
                "Infinity",
                "1e3",
                "1_000",
                "+5",
                ".5",
                "5.",
                "010",
                " 5",
            ]
        ),
        (True, "is not a decimal number"),
        (0.1, "is not a decimal number"),
    ],
)
def test_quantity_refuses_anything_but_plain_decimals(value: object, problem: str):
    with pytest.raises(ValidationError, match=f"Value error, {problem} "):
        quantity.validate_python(value)


def test_quantity_refuses_more_than_3_places():
    with pytest.raises(ValidationError, match="has more than 3 places"):
        quantity.validate_python("40.0001")


def test_periods_accept_a_whole_number_or_its_text():
    assert periods.validate_python(4) == 4
    assert periods.validate_python("4") == 4
    assert type(periods.validate_python("4")) is int


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("4.0", "is not a whole number"),
        (Decimal("4.0"), "is not a whole number"),
        (True, "is not a decimal number"),
        (4.0, "is not a decimal number"),
    ],
)
def test_periods_refuse_anything_but_whole_numbers(value: object, problem: str):
    with pytest.raises(ValidationError, match=f"Value error, {problem} "):
        periods.validate_python(value)


@pytest.mark.parametrize("value", [7, "7", 2**128 - 1])
def test_seed_takes_a_whole_number_from_0_or_its_text(value: object):
    assert seed.validate_python(value) == int(str(value))


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        (7.0, "is not a whole number"),
        (-1, r"is not from 0 to 2 \*\* 128 - 1"),
        (1.5, "is not a whole number"),
        ("1.5", "is not a whole number"),
        (2**128, r"is not from 0 to 2 \*\* 128 - 1"),
        (True, "is not a whole number"),
    ],
)
def test_seed_refuses_anything_else(value: object, problem: str):
    with pytest.raises(ValidationError, match=f"Value error, {problem} "):
        seed.validate_python(value)


def test_reader_takes_numbers_from_their_text():
    result = read_json_bytes(
        b'{"share": 0.0050, "periods": 7, "quoted": "7", "seed": 7}'
    )

    assert result == {
        "share": Decimal("0.0050"),
        "periods": 7,
        "quoted": "7",
        "seed": 7,
    }
    fields = cast(dict[str, Any], result)
    assert fields["share"].as_tuple() == Decimal("0.0050").as_tuple()
    assert type(fields["periods"]) is int
    assert read_json_bytes(b"0.1") == Decimal("0.1")


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            b'{"catalogue": {"microchip": 1, "resistor": 2, "microchip": 3}}',
            "catalogue.microchip: duplicate key",
        ),
        (b'{"a": [1, 1e3]}', "a.1: is not a plain decimal number"),
        (b'{"b": NaN}', "b: is not a finite number"),
        (b'{"b": Infinity}', "b: is not a finite number"),
        (b"\xff\xfe", "body: is not UTF-8"),
        (b"{not json", "body: is not JSON"),
        (b'{"order": "\\ud800"}', "order: is not valid text"),
        (b'"\\ud800"', "body: is not valid text"),
        (
            b'{"decisions": [{"\\ud800": 1}]}',
            "decisions.0: holds a key that is not valid text",
        ),
    ],
)
def test_reader_refuses_a_bad_body_with_its_path(body: bytes, error: str):
    with pytest.raises(InputError) as refusal:
        read_json_bytes(body)
    assert str(refusal.value) == error


def test_a_body_nested_5000_levels_is_refused():
    with pytest.raises(InputError) as refusal:
        read_json_bytes(b"[" * 5000 + b"]" * 5000)
    assert str(refusal.value) == "body: is nested too deeply"


def test_the_reader_keeps_a_letter_written_as_an_escape():
    assert read_json_bytes(b'{"name": "\\u00e9"}') == {"name": "\u00e9"}


def test_first_model_error_becomes_an_input_error_with_its_path():
    body = {
        "period": 1,
        "decisions": [{"kind": "ship", "order": "order-1-1", "quantity": "1.0001"}],
    }

    with pytest.raises(InputError, match=r"^decisions\.0\.quantity: "):
        validate(DecisionsCreate, body)


def test_a_number_of_more_than_50_digits_once_rounded_is_refused():
    with pytest.raises(ValueError, match=r"^has more than 50 digits$"):
        read_number("1" + "0" * 47, 3)


def test_a_number_of_50_digits_once_rounded_is_read():
    number = read_number("1" + "0" * 46, 3)

    assert number.as_tuple().exponent == -3
    assert number == Decimal("1" + "0" * 46)


def test_a_duplicate_key_is_refused_with_its_path():
    text = write_json(tiny_manifest()).decode()
    chip = text[text.index('"chip":{') : text.index("}", text.index('"chip":{')) + 1]
    body = text.replace(chip, chip + "," + chip, 1).encode()

    with pytest.raises(InputError) as refusal:
        read_json_bytes(body)

    assert str(refusal.value) == "materials.chip: duplicate key"


def test_a_duplicate_key_at_the_top_is_refused_with_its_name():
    text = write_json(tiny_scenario()).decode()
    body = text.replace('"horizon":5', '"horizon":5,"horizon":5', 1).encode()

    with pytest.raises(InputError) as refusal:
        read_json_bytes(body)

    assert str(refusal.value) == "horizon: duplicate key"


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(st.decimals(min_value=-(10**46), max_value=10**46, places=3))
def test_quantity_gives_3_places_equal_to_its_text(value: Decimal):
    text = format(value, "f")
    result = quantity.validate_python(text)
    assert result == value
    assert result.as_tuple().exponent == -3


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(st.floats())
def test_quantity_refuses_every_float(value: float):
    with pytest.raises(ValidationError, match="Value error, is not a decimal number "):
        quantity.validate_python(value)
