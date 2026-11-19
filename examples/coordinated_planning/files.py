"""The output files of the example: JSON documents and JSON lines kept on disk.

Examples:
    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as folder:
    ...     path = Path(folder) / "status.json"
    ...     write_json(path, {"status": "complete"})
    ...     json.loads(path.read_text())["status"]
    'complete'
"""

import json
import os
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    """Write a value as indented JSON, replacing the file only once it is on disk.

    Args:
        path (Path): The file to write.
        value (object): The value; decimals and other values are written as text.

    Examples:
        >>> from decimal import Decimal
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     path = Path(folder) / "cost.json"
        ...     write_json(path, {"cost": Decimal("0.5")})
        ...     json.loads(path.read_text())
        {'cost': '0.5'}
    """
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        stream.write(json.dumps(value, default=str, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def append_json_line(path: Path, value: object) -> None:
    """Append a value as one JSON line and keep it on disk before returning.

    Args:
        path (Path): The JSON lines file.
        value (object): The value; decimals and other values are written as text.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     path = Path(folder) / "events.jsonl"
        ...     append_json_line(path, {"kind": "attempt-start"})
        ...     append_json_line(path, {"kind": "attempt-end"})
        ...     len(path.read_text().splitlines())
        2
    """
    with path.open("a") as stream:
        stream.write(json.dumps(value, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
