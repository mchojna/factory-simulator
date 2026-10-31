"""The random streams of a run: a stream per key and the uniform numbers drawn from it.

Examples:
    >>> 0 <= draw_uniform(open_stream(7, "demand", "distributor", "monitor")) < 1
    True
"""

import hashlib
from decimal import Decimal

from numpy.random import PCG64, Generator, SeedSequence

from factory_simulator.engine.numbers import in_decimal_context


@in_decimal_context
def open_stream(seed: int, *key: str) -> Generator:
    """Open the random stream of a source, named by the parts of its key.

    Args:
        seed (int): The seed of the run.
        *key (str): The parts of the key, such as "demand", a customer and a product.

    Returns:
        Generator: The stream, the same for the same seed and key.

    Examples:
        >>> first = open_stream(7, "demand", "distributor", "monitor").random()
        >>> first == open_stream(7, "demand", "distributor", "monitor").random()
        True
    """
    digest = hashlib.sha256("/".join(key).encode("utf-8")).digest()
    key_numbers = [
        int.from_bytes(digest[position : position + 4], "big")
        for position in range(0, 16, 4)
    ]
    return Generator(PCG64(SeedSequence(entropy=seed, spawn_key=key_numbers)))


def draw_uniform(stream: Generator) -> Decimal:
    """Draw one uniform number from 0 to 1 as a decimal.

    Args:
        stream (Generator): The stream to draw from.

    Returns:
        Decimal: The number, with the digits of its shortest text.

    Examples:
        >>> 0 <= draw_uniform(open_stream(0, "test")) < 1
        True
    """
    return Decimal(repr(stream.random()))
