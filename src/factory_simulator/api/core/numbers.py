"""The numbers of the HTTP interface: their types, the reader of JSON and validation.

Examples:
    >>> read_json_bytes(b'{"price": 3.50}')
    {'price': Decimal('3.50')}
"""

import json
import re
from collections.abc import Mapping
from decimal import Decimal
from functools import partial
from types import MappingProxyType
from typing import Annotated, TypeVar, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    SerializerFunctionWrapHandler,
    Strict,
    ValidationError,
    WithJsonSchema,
    WrapSerializer,
)

from factory_simulator.engine import CONTEXT, InputError, in_decimal_context

NUMBER_TEXT = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
WHOLE_TEXT = re.compile(r"-?(0|[1-9][0-9]*)")
LARGEST_SEED = 2**128 - 1
# The tags of a parameter given as a fixed number or as a range. They hold a space, so
# no identifier of a manifest equals them.
FIXED_TAG = "fixed value"
RANGE_TAG = "range value"
# The tags of a range by its distribution.
DISTRIBUTION_TAGS = (
    "uniform range",
    "triangular range",
    "normal range",
    "lognormal range",
)
NUMBER_SCHEMA = WithJsonSchema({"type": "number"})
# A body takes a number as a JSON number or as its text; an answer writes a JSON
# number.
BODY_NUMBER_SCHEMA = WithJsonSchema(
    {
        "anyOf": [
            {"type": "number"},
            {"type": "string", "pattern": f"^{NUMBER_TEXT.pattern}$"},
        ]
    },
    mode="validation",
)
BODY_WHOLE_SCHEMA = WithJsonSchema(
    {
        "anyOf": [
            {"type": "integer"},
            {"type": "string", "pattern": f"^{WHOLE_TEXT.pattern}$"},
        ]
    },
    mode="validation",
)
ANSWER_NUMBER_SCHEMA = WithJsonSchema({"type": "number"}, mode="serialization")
ANSWER_WHOLE_SCHEMA = WithJsonSchema({"type": "integer"}, mode="serialization")


class StrictModel(BaseModel):
    """A model that is frozen, strict and refuses unknown keys.

    Examples:
        >>> StrictModel.model_config["extra"]
        'forbid'
    """

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
        serialize_by_alias=True,
    )


@in_decimal_context
def read_number(value: object, places: int) -> Decimal:
    """Read a number and bring it to exactly the given places.

    Args:
        value (object): A `Decimal`, a whole number or a plain decimal text such as
            "40.5".
        places (int): Places after the point.

    Returns:
        Decimal: The number with exactly `places` places.

    Raises:
        ValueError: If the value is not a finite number in one of these forms, or has
            more places, or more than 50 digits once rounded to its places.

    Examples:
        >>> read_number("40.5", 3)
        Decimal('40.500')
        >>> read_number(7, 4)
        Decimal('7.0000')
    """
    if isinstance(value, str):
        if NUMBER_TEXT.fullmatch(value) is None:
            raise ValueError("is not a plain decimal number")
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    elif isinstance(value, int) and not isinstance(value, bool):
        number = Decimal(value)
    else:
        raise ValueError("is not a decimal number")
    if not number.is_finite():
        raise ValueError("is not a finite number")
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        if places == 0:
            raise ValueError("is not a whole number")
        raise ValueError(f"has more than {places} places")
    if number.adjusted() + 1 + places > CONTEXT.prec:
        raise ValueError(f"has more than {CONTEXT.prec} digits")
    return number.quantize(Decimal(1).scaleb(-places))


def read_whole_number(value: object) -> int:
    """Read a whole number, such as a count of periods or of objects.

    Args:
        value (object): A whole number or its text, such as "4".

    Returns:
        int: The number.

    Raises:
        ValueError: If the value is not a whole number or its text.

    Examples:
        >>> read_whole_number("4")
        4
    """
    return int(read_number(value, 0))


def read_seed(value: object) -> int:
    """Read a seed: a whole number from 0 to `2 ** 128 - 1`, or its text.

    Args:
        value (object): The seed as sent.

    Returns:
        int: The seed.

    Raises:
        ValueError: If the value is not such a whole number.

    Examples:
        >>> read_seed("7")
        7
    """
    if isinstance(value, str) and WHOLE_TEXT.fullmatch(value) is not None:
        # The largest seed has 39 digits; a longer text is refused before it is read.
        if len(value.removeprefix("-")) > len(str(LARGEST_SEED)):
            raise ValueError("is not from 0 to 2 ** 128 - 1")
        number = int(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        number = value
    else:
        raise ValueError("is not a whole number")
    if not 0 <= number <= LARGEST_SEED:
        raise ValueError("is not from 0 to 2 ** 128 - 1")
    return number


# A quantity: a number with 3 places, or its text.
Quantity = Annotated[
    Decimal,
    BeforeValidator(partial(read_number, places=3)),
    BODY_NUMBER_SCHEMA,
    ANSWER_NUMBER_SCHEMA,
]
# An amount of money: a number with 4 places, or its text.
Money = Annotated[
    Decimal,
    BeforeValidator(partial(read_number, places=4)),
    BODY_NUMBER_SCHEMA,
    ANSWER_NUMBER_SCHEMA,
]
# A share: a number with 4 places, or its text.
Share = Annotated[
    Decimal,
    BeforeValidator(partial(read_number, places=4)),
    BODY_NUMBER_SCHEMA,
    ANSWER_NUMBER_SCHEMA,
]
# A number of periods: a whole number or its text.
Periods = Annotated[
    int, BeforeValidator(read_whole_number), BODY_WHOLE_SCHEMA, ANSWER_WHOLE_SCHEMA
]
# A seed: a whole number from 0 to `2 ** 128 - 1`, or its text.
Seed = Annotated[
    int, BeforeValidator(read_seed), BODY_WHOLE_SCHEMA, ANSWER_WHOLE_SCHEMA
]
# A number the HTTP interface answers, with any number of places. It is read lax, so a
# JSON whole number reads as a decimal too.
ExactNumber = Annotated[Decimal, Strict(False), NUMBER_SCHEMA]
# A count of objects, read like a number of periods.
Count = Periods


def list_to_tuple(value: object) -> object:
    """List the items of a list in a tuple, and leave every other value as it is.

    Args:
        value (object): Any value.

    Returns:
        object: A tuple of the items of a list, or the value itself.

    Examples:
        >>> list_to_tuple([1, 2])
        (1, 2)
    """
    if isinstance(value, list):
        return tuple(cast(list[object], value))
    return value


def write_mapping(
    value: Mapping[object, object], handler: SerializerFunctionWrapHandler
) -> object:
    """Write a read-only mapping as a dictionary, its values written too.

    Args:
        value (Mapping[object, object]): The mapping.
        handler (SerializerFunctionWrapHandler): Pydantic's dump of a dictionary.

    Returns:
        object: The dumped dictionary.

    Examples:
        >>> write_mapping(MappingProxyType({"a": 1}), lambda value: value)
        {'a': 1}
    """
    return handler(dict(value))


Key = TypeVar("Key")
Value = TypeVar("Value")
Item = TypeVar("Item")

ReadOnlyMapping = Annotated[
    Mapping[Key, Value],
    AfterValidator(MappingProxyType),
    WrapSerializer(write_mapping),
]
ReadOnlyList = Annotated[tuple[Item, ...], BeforeValidator(list_to_tuple)]


class BadNumber:
    """A number of a body that is not plain decimal text or not finite.

    Attributes:
        problem (str): What is wrong with it.

    Examples:
        >>> BadNumber("is not a finite number").problem
        'is not a finite number'
    """

    def __init__(self, problem: str) -> None:
        """Keep the problem of the number.

        Args:
            problem (str): What is wrong with it.

        Examples:
            >>> BadNumber("is not a finite number").problem
            'is not a finite number'
        """
        self.problem = problem


class Pairs(list[tuple[str, object]]):
    """The key and value pairs of one JSON object, in the order of the body.

    Examples:
        >>> Pairs([("b", 1), ("a", 2)])[0]
        ('b', 1)
    """


def read_float_text(text: str) -> Decimal | BadNumber:
    """Read the text of a JSON number with a point or an exponent.

    Args:
        text (str): The text of the number.

    Returns:
        Decimal | BadNumber: The decimal, or a marker of a number in another form.

    Examples:
        >>> read_float_text("0.0050")
        Decimal('0.0050')
    """
    if NUMBER_TEXT.fullmatch(text) is None:
        return BadNumber("is not a plain decimal number")
    return Decimal(text)


def read_int_text(text: str) -> int | BadNumber:
    """Read the text of a JSON whole number.

    Args:
        text (str): The text of the number.

    Returns:
        int | BadNumber: The whole number, or a marker of a number in another form
            or of more than 50 digits.

    Examples:
        >>> read_int_text("7")
        7
    """
    if WHOLE_TEXT.fullmatch(text) is None:
        return BadNumber("is not a plain decimal number")
    if len(text.removeprefix("-")) > CONTEXT.prec:
        return BadNumber(f"has more than {CONTEXT.prec} digits")
    return int(text)


def read_constant(text: str) -> BadNumber:  # noqa: ARG001
    """Read `NaN`, `Infinity` and `-Infinity` as a bad number.

    Args:
        text (str): The constant.

    Returns:
        BadNumber: A marker of a number that is not finite.

    Examples:
        >>> read_constant("NaN").problem
        'is not a finite number'
    """
    return BadNumber("is not a finite number")


@in_decimal_context
def read_json_bytes(body: bytes) -> object:
    r"""Read a JSON body from its bytes, taking every number from its text.

    Args:
        body (bytes): The raw body.

    Returns:
        object: Dictionaries, lists, text, whole numbers, decimals, booleans and None.

    Raises:
        InputError: If the body is not UTF-8, not JSON or nested too deeply, or
            holds a number in another form, a constant such as `NaN`, a key twice, or
            text that is not valid Unicode; with its path.

    Examples:
        >>> read_json_bytes(b'{"quantity": 40.5, "period": 2}')
        {'quantity': Decimal('40.5'), 'period': 2}
        >>> read_json_bytes(b'{"order": "\\ud800"}')
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: order: is not valid text
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("body: is not UTF-8") from None
    try:
        document = json.loads(
            text,
            parse_float=read_float_text,
            parse_int=read_int_text,
            parse_constant=read_constant,
            object_pairs_hook=Pairs,
        )
    except json.JSONDecodeError:
        raise InputError("body: is not JSON") from None
    except RecursionError:
        raise InputError("body: is nested too deeply") from None
    try:
        return build_value(document, "")
    except RecursionError:
        raise InputError("body: is nested too deeply") from None


def build_value(value: object, path: str) -> object:
    """Build dictionaries from the pairs of a body and refuse its first marker.

    Args:
        value (object): A value read by `json.loads`.
        path (str): The dotted path of the value; empty for the whole body.

    Returns:
        object: The value with dictionaries in place of pairs.

    Raises:
        InputError: If a number is bad, a constant appears, a key repeats, or a text
            or a key is not valid Unicode, at the first one.

    Examples:
        >>> build_value(Pairs([("lines", [Pairs([("id", "smt")])])]), "")
        {'lines': [{'id': 'smt'}]}
    """
    if isinstance(value, BadNumber):
        raise InputError(f"{path or 'body'}: {value.problem}")
    if isinstance(value, str) and not is_valid_text(value):
        raise InputError(f"{path or 'body'}: is not valid text")
    if isinstance(value, Pairs):
        mapping: dict[str, object] = {}
        for key, item in value:
            # The path of the object, so the detail never holds the bad text.
            if not is_valid_text(key):
                raise InputError(
                    f"{path or 'body'}: holds a key that is not valid text"
                )
            key_path = join_path(path, key)
            if key in mapping:
                raise InputError(f"{key_path}: duplicate key")
            mapping[key] = build_value(item, key_path)
        return mapping
    if isinstance(value, list):
        items = cast(list[object], value)
        return [
            build_value(item, join_path(path, str(position)))
            for position, item in enumerate(items)
        ]
    return value


def is_valid_text(text: str) -> bool:
    r"""Tell whether a text is valid Unicode, so that it encodes as UTF-8.

    Args:
        text (str): A text read by `json.loads`, which may hold a lone surrogate.

    Returns:
        bool: True when the text encodes as UTF-8.

    Examples:
        >>> is_valid_text("\u00e9"), is_valid_text("\ud800")
        (True, False)
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def join_path(path: str, key: str) -> str:
    """Join a key to a dotted path.

    Args:
        path (str): The dotted path, empty for the top.
        key (str): The key or list position to add.

    Returns:
        str: The longer path.

    Examples:
        >>> join_path("catalogue", "microchip")
        'catalogue.microchip'
        >>> join_path("", "lines")
        'lines'
    """
    if not path:
        return key
    return f"{path}.{key}"


def validate[M: BaseModel](model: type[M], value: object) -> M:
    """Validate a value read from a body with a model.

    Args:
        model (type[M]): The model.
        value (object): The value read by `read_json_bytes`.

    Returns:
        M: The validated model.

    Raises:
        InputError: If the value breaks the model; the text is the path and problem
            of the first error.

    Examples:
        >>> from factory_simulator.api.schemas.manifest import Route
        >>> validate(Route, {"cost": "0.8", "lead_time": 1}).cost
        Decimal('0.8000')
    """
    try:
        return model.model_validate(value)
    except ValidationError as error:
        first = error.errors()[0]
        path = error_path(first["loc"], value)
        problem = str(first["msg"]).removeprefix("Value error, ")
        raise InputError(f"{path}: {problem}") from None


def error_path(location: tuple[int | str, ...], value: object) -> str:
    """Give the dotted path of the location of a pydantic error.

    The path leaves out four parts of the location:

    - a leading `body`;
    - the marker `[key]`;
    - the tag of a union that pydantic puts after a list position, found as the
      `kind` of that item;
    - the tags of a parameter given as a fixed number or a range, and of the
      distribution of a range.

    Args:
        location (tuple[int | str, ...]): The location of the error.
        value (object): The value that was validated.

    Returns:
        str: The dotted path.

    Examples:
        >>> error_path(
        ...     ("decisions", 0, "ship", "quantity"), {"decisions": [{"kind": "ship"}]}
        ... )
        'decisions.0.quantity'
    """
    parts: list[str] = []
    current: object = value
    skip_tag = False
    for part in location:
        if part == "[key]":
            continue
        if skip_tag and kind_of(current) == part:
            skip_tag = False
            continue
        if part in (FIXED_TAG, RANGE_TAG, *DISTRIBUTION_TAGS):
            continue
        skip_tag = isinstance(part, int)
        parts.append(str(part))
        current = step_into(current, part)
    if parts[:1] == ["body"] and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts) or "body"


def kind_of(value: object) -> object:
    """Give the `kind` of a mapping, or None for any other value.

    Args:
        value (object): A value of a body.

    Returns:
        object: The value of its key `kind`, or None.

    Examples:
        >>> kind_of({"kind": "ship"})
        'ship'
    """
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value).get("kind")
    return None


def step_into(value: object, part: int | str) -> object:
    """Step from a value into one of its members, or into nothing.

    Args:
        value (object): A mapping, a list or any other value.
        part (int | str): The key or position.

    Returns:
        object: The member, or None when there is none.

    Examples:
        >>> step_into({"a": [5]}, "a")
        [5]
    """
    if isinstance(value, Mapping) and isinstance(part, str):
        return cast(Mapping[str, object], value).get(part)
    if isinstance(value, list | tuple) and isinstance(part, int):
        items = cast(list[object] | tuple[object, ...], value)
        return items[part] if 0 <= part < len(items) else None
    return None
