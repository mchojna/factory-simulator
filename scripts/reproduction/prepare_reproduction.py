"""The extraction of the evidence archive: its digest, members and inventory check.

Examples:
    >>> main(["--output", "evidence"])
    Traceback (most recent call last):
    ...
    SystemExit: 2
"""

import argparse
from pathlib import Path

from examples.coordinated_planning.evidence import extract


def main(arguments: list[str] | None = None) -> None:
    """Extract the evidence archive into a new folder and check its inventory.

    Args:
        arguments (list[str] | None, optional): The command line arguments; those of
            the process when not given.

    Examples:
        >>> main(["--archive", "missing.zip", "--output", "evidence"])
        Traceback (most recent call last):
        ...
        FileNotFoundError: missing.zip: archive does not exist
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, required=True, help="the evidence archive"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="a new directory of the package"
    )
    options = parser.parse_args(arguments)
    package = extract(options.output, options.archive)
    print(f"package checked: {package}")


if __name__ == "__main__":
    main()
