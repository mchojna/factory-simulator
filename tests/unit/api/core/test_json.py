import json
from decimal import Decimal

import pytest
from factories import example_count
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json


def make_decimal(sign: int, digits: list[int], exponent: int) -> Decimal:
    return Decimal((sign, tuple(digits), exponent))


# Independent canonical text: plain digits, no trailing zeros, no negative zero.
def canonical_text(value: Decimal) -> str:
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    number = "".join(map(str, digits))
    if exponent >= 0:
        number = number + "0" * exponent
    else:
        number = number.rjust(-exponent + 1, "0")
        number = number[:exponent] + "." + number[exponent:]
        number = number.rstrip("0").rstrip(".")
    number = number.lstrip("0") or "0"
    if number.startswith("."):
        number = "0" + number
    if number == "0":
        return "0"
    return ("-" if sign else "") + number


finite_decimals = st.builds(
    make_decimal,
    st.sampled_from([0, 1]),
    st.lists(st.integers(min_value=0, max_value=9), min_size=1, max_size=50),
    st.integers(min_value=-60, max_value=10),
)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("6E-8"), b"0.00000006"),
        (Decimal("1E+3"), b"1000"),
        (Decimal("-0.000"), b"0"),
        (Decimal("-12.50"), b"-12.5"),
    ],
)
def test_decimal_is_written_in_canonical_form(value: Decimal, text: bytes):
    assert write_json(value) == text


def test_writer_gives_compact_sorted_json_with_canonical_decimals():
    value = {
        "b": [Decimal("40.000"), Decimal("1.500000000000"), Decimal("0.123456789012")],
        "a": True,
        "c": chr(233),
    }

    assert (
        write_json(value)
        == ('{"a":true,"b":[40,1.5,0.123456789012],"c":"' + chr(233) + '"}').encode()
    )


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(finite_decimals)
def test_writer_gives_the_canonical_text_of_every_decimal(value: Decimal):
    text = write_json([value]).decode("utf-8")
    result = json.loads(text, parse_float=Decimal, parse_int=Decimal)[0]
    assert result == value
    assert "e" not in text.lower()
    assert text == "[" + canonical_text(value) + "]"
