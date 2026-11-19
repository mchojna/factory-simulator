"""The evidence archive: its extraction, its inventory and the folders of its cases.

Examples:
    >>> CASE_FOLDERS["A3"]
    'integration/2026-11-12/A'
"""

import hashlib
import json
import os
import socket
import stat
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

# The folder every member of the archive sits in.
PREFIX = "Factory-Simulator-Reproduction"
# The manifest of the package: the SHA-256 digest of every other file.
MANIFEST = "SHA256SUMS.json"
# The folder of each case in the package.
CASE_FOLDERS = {
    "A3": "integration/2026-11-12/A",
    "B3": "integration/2026-11-12/B",
    "C1": "integration/2026-11-13/C1",
    "C2": "integration/2026-11-13/C2",
}
# The files an operating system adds that the inventory leaves out.
_IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db"})
# The environment variables of provider credentials.
_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def extract(destination: Path, archive: Path) -> Path:
    """Extract the evidence archive into a new folder and run its inventory check.

    Args:
        destination (Path): The new folder.
        archive (Path): The evidence archive.

    Returns:
        Path: The extracted package folder.

    Raises:
        FileNotFoundError: If the archive does not exist.
        ValueError: If a member path leaves the package folder or a file differs from
            the manifest of the package.
        FileExistsError: If the destination exists.

    Examples:
        >>> extract(Path("evidence"), Path("missing.zip"))
        Traceback (most recent call last):
        ...
        FileNotFoundError: missing.zip: archive does not exist
    """
    destination = destination.resolve()
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"{archive.name}: archive does not exist")
    if destination.exists():
        raise FileExistsError(f"output already exists: {destination}")
    with zipfile.ZipFile(archive) as opened:
        for member in opened.infolist():
            name = Path(member.filename)
            if name.is_absolute() or ".." in name.parts or name.parts[0] != PREFIX:
                raise ValueError(f"{member.filename}: path leaves {PREFIX}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"{member.filename}: is a symbolic link")
        destination.mkdir(parents=True)
        opened.extractall(destination)
    package = destination / PREFIX
    differences = inventory_differences(package)
    if differences:
        raise ValueError(
            f"{MANIFEST}: {len(differences)} files differ, first {differences[0]}"
        )
    return package


def inventory_differences(package: Path) -> list[str]:
    """Give the files of a package that are changed, missing or not in its manifest.

    Args:
        package (Path): The extracted package folder.

    Returns:
        list[str]: The paths, relative to the package, in sorted order.

    Raises:
        FileNotFoundError: If the package has no manifest.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     package = Path(folder)
        ...     _ = (package / "README.txt").write_text("guide")
        ...     _ = (package / MANIFEST).write_text("{}")
        ...     inventory_differences(package)
        ['README.txt']
    """
    expected: dict[str, str] = json.loads((package / MANIFEST).read_text())
    actual = {
        path.relative_to(package).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in package.rglob("*")
        if path.is_file()
        and path.name not in _IGNORED_NAMES
        and path.relative_to(package).as_posix() != MANIFEST
    }
    return sorted(
        name
        for name in expected.keys() | actual.keys()
        if expected.get(name) != actual.get(name)
    )


def case_folder(package: Path, case: str) -> Path:
    """Give the folder of the saved calls and results of a case.

    Args:
        package (Path): The extracted package folder.
        case (str): The case: A3, B3, C1 or C2.

    Returns:
        Path: The case folder.

    Examples:
        >>> case_folder(Path("evidence"), "C1").name
        'C1'
    """
    return package / CASE_FOLDERS[case]


@contextmanager
def offline_network() -> Generator[None]:
    """Refuse every socket connection and hide the provider credentials.

    Yields:
        None: Control while connections are refused.

    Raises:
        RuntimeError: If code inside opens a connection.

    Examples:
        >>> with offline_network():
        ...     socket.create_connection(("127.0.0.1", 9))
        Traceback (most recent call last):
        ...
        RuntimeError: network: connections are refused offline
    """
    saved = {key: os.environ.pop(key) for key in _PROVIDER_KEYS if key in os.environ}
    connect, create_connection = socket.socket.connect, socket.create_connection

    def refuse(*_arguments: object, **_keywords: object) -> NoReturn:
        raise RuntimeError("network: connections are refused offline")

    socket.socket.connect = refuse
    socket.create_connection = refuse
    try:
        yield
    finally:
        socket.socket.connect, socket.create_connection = connect, create_connection
        os.environ.update(saved)
