"""The examples of the package: the example manifest and its scenarios, made at start.

Examples:
    >>> EXAMPLES.name
    'examples'
"""

from pathlib import Path

from sqlalchemy.orm import Session

from factory_simulator.api.services.manifests import create_manifest
from factory_simulator.api.services.scenarios import create_scenario

EXAMPLES = Path(__file__).parents[1] / "examples"
MANIFEST_FILE = "manifest.json"


def create_examples(session: Session) -> None:
    """Create the example manifest, then each scenario of the library for it.

    Each goes through the checks of a manifest or scenario sent by a client; one
    already stored under the identifier of its content is not created again.

    Args:
        session (Session): The session; the function commits.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services.manifests import list_manifests
        >>> create_examples(session)
        >>> listed = list_manifests(session)["manifests"]
        >>> sorted(manifest["name"] for manifest in listed)
        ['Electronics factory with economies of scale']
    """
    _, manifest = create_manifest(session, (EXAMPLES / MANIFEST_FILE).read_bytes())
    for path in sorted((EXAMPLES / "scenarios").glob("*.json")):
        create_scenario(session, str(manifest["id"]), path.read_bytes())
