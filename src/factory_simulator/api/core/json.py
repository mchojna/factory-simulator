"""The one writer of JSON: responses and canonical JSON with exact decimals.

Examples:
    >>> write_json({"quantity": Decimal("40.500")})
    b'{"quantity":40.5}'
"""

from collections.abc import Mapping
from decimal import Decimal
from json.encoder import encode_basestring
from typing import cast

from pydantic import BaseModel

from factory_simulator.engine import in_decimal_context


def decimal_text(value: Decimal) -> str:
    """Write a decimal in its canonical form.

    The form is plain positional notation without an exponent, with trailing zeros
    removed and negative zero written as 0.

    Args:
        value (Decimal): A finite decimal.

    Returns:
        str: The canonical text.

    Examples:
        >>> decimal_text(Decimal("40.000"))
        '40'
        >>> decimal_text(Decimal("6E-8"))
        '0.00000006'
        >>> decimal_text(Decimal("-0.000"))
        '0'
    """
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@in_decimal_context
def write_json(value: object) -> bytes:
    """Write a value as canonical JSON.

    Canonical JSON has compact separators, sorted keys, UTF-8 text without escapes of
    non-ASCII characters and decimals in their canonical form.

    Args:
        value (object): A model, or mappings, lists, tuples, text, whole numbers,
            decimals, booleans and None, nested in any way.

    Returns:
        bytes: The JSON text in UTF-8.

    Raises:
        TypeError: If the value holds anything else, such as a `float`.

    Examples:
        >>> write_json({"price": Decimal("0.00230"), "item": "resistor"})
        b'{"item":"resistor","price":0.0023}'
    """
    return json_value_text(value).encode("utf-8")


def json_value_text(value: object) -> str:
    """Write one value as compact JSON text.

    Args:
        value (object): A value as `write_json` takes it.

    Returns:
        str: The JSON text.

    Raises:
        TypeError: If the value holds anything `write_json` does not take.

    Examples:
        >>> json_value_text([1, Decimal("2.50"), None, True, {"b": "\u00e9", "a": []}])
        '[1,2.5,null,true,{"a":[],"b":"\u00e9"}]'
    """
    parts: list[str] = []
    write_value(value, parts)
    return "".join(parts)


def write_value(value: object, parts: list[str]) -> None:
    """Write the JSON text of one value into the parts of a text.

    Text is escaped as `json.dumps` escapes it without ASCII escapes, keys are sorted,
    and decimals take their canonical form.

    Args:
        value (object): A value as `write_json` takes it.
        parts (list[str]): The parts written so far; the value is appended.

    Raises:
        TypeError: If the value holds anything `write_json` does not take.

    Examples:
        >>> parts = ["["]
        >>> write_value(Decimal("2.50"), parts)
        >>> "".join(parts)
        '[2.5'
    """
    if isinstance(value, str):
        parts.append(encode_basestring(value))
    elif isinstance(value, Decimal):
        parts.append(decimal_text(value))
    elif value is None:
        parts.append("null")
    elif value is True:
        parts.append("true")
    elif value is False:
        parts.append("false")
    elif isinstance(value, int):
        parts.append(int.__repr__(value))
    elif isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        parts.append("{")
        for position, key in enumerate(sorted(mapping)):
            if position:
                parts.append(",")
            parts.append(encode_basestring(key))
            parts.append(":")
            write_value(mapping[key], parts)
        parts.append("}")
    elif isinstance(value, list | tuple):
        items = cast(list[object] | tuple[object, ...], value)
        parts.append("[")
        for position, item in enumerate(items):
            if position:
                parts.append(",")
            write_value(item, parts)
        parts.append("]")
    elif isinstance(value, BaseModel):
        write_value(value.model_dump(mode="python"), parts)
    else:
        raise TypeError(f"cannot write {value!r} as JSON")
