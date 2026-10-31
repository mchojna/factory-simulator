"""The inspect a record demo command: read the export of a finished run offline.

Examples:
    >>> demo_parser(DEMO_NAME, accepts_archive=True).prog
    'inspect-a-record'
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from demos.inspect_a_record import DEMO_NAME
from demos.utils.cli import demo_parser, write_inspection

REQUIRED_FILES = {
    "manifest.json",
    "scenario.json",
    "run.json",
    "periods.parquet",
    "results.parquet",
}


def main() -> None:
    """Read the export of a finished run and write an offline summary.

    Examples:
        >>> demo_parser(DEMO_NAME, accepts_archive=True).prog
        'inspect-a-record'
    """
    arguments = demo_parser(DEMO_NAME, accepts_archive=True).parse_args()
    record = _inspection_of(arguments.archive)
    path = write_inspection(DEMO_NAME, record["run_id"], record, arguments.output)
    print(path)


def _inspection_of(path: Path) -> dict[str, Any]:
    """Give the identifiers and member names of the export of a finished run.

    Args:
        path (Path): The export ZIP of the run.

    Returns:
        dict[str, Any]: The run and scenario identifiers, the seed, the manifest and
            scenario names, the member names and the SHA-256 of the export.

    Raises:
        ValueError: If the export is damaged or misses required members.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(path) as archive:
            damaged = archive.testzip()
            if damaged is not None:
                raise ValueError(f"archive contains a damaged member: {damaged}")
            names = set(archive.namelist())
            missing = REQUIRED_FILES - names
            if missing:
                raise ValueError(f"archive is missing: {', '.join(sorted(missing))}")
            run = json.loads(archive.read("run.json"))
            manifest = json.loads(archive.read("manifest.json"))
            scenario = json.loads(archive.read("scenario.json"))
    except zipfile.BadZipFile as error:
        raise ValueError(f"not a valid run ZIP: {path}") from error

    return {
        "run_id": run["id"],
        "seed": run["seed"],
        "scenario_id": run["scenario_id"],
        "manifest_name": manifest["name"],
        "scenario_name": scenario["name"],
        "files": sorted(names),
        "sha256": digest,
    }


if __name__ == "__main__":
    main()
