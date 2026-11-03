"""The service of manifests: create, generate, list and read manifests.

Examples:
    >>> len(content_id({"name": "Electronics factory"}))
    64
"""

import hashlib

from sqlalchemy.orm import Session

from factory_simulator import engine
from factory_simulator.api.core.errors import NotFoundError
from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.repositories import manifests
from factory_simulator.api.schemas.manifest import ManifestGenerate
from factory_simulator.api.services.readers.manifest import (
    resolve_manifest,
    to_factory,
    written_content,
)


def content_id(content: object) -> str:
    """Give the identifier of a content: the SHA-256 digest of its canonical JSON.

    Args:
        content (object): The content.

    Returns:
        str: 64 hexadecimal digits.

    Examples:
        >>> content_id({"b": 1, "a": 2}) == content_id({"a": 2, "b": 1})
        True
    """
    return hashlib.sha256(write_json(content)).hexdigest()


def create_manifest(session: Session, body: bytes) -> tuple[int, dict[str, object]]:
    """Create a manifest, or find the same one already stored.

    Args:
        session (Session): The session of the request.
        body (bytes): The raw body.

    Returns:
        tuple[int, dict[str, object]]: 201 and the new manifest, or 200 and the
            stored one.

    Raises:
        InputError: If the body is not a valid manifest.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _ = create_manifest(session, manifest_body)
        >>> create_manifest(session, manifest_body)[0]
        200
    """
    model, origins = resolve_manifest(read_json_bytes(body))
    factory = to_factory(model, origins)
    engine.check_factory(factory)
    content = written_content(model, origins)
    manifest = Manifest(
        id=content_id(content),
        content=content,
        linear=engine.is_linear(factory),
    )
    created = manifests.add_manifest(session, manifest)
    return (201 if created else 200), read_manifest(session, manifest.id)


def generate_manifest(session: Session, body: bytes) -> tuple[int, dict[str, object]]:
    """Generate a manifest from counts and a seed, then create it like any other.

    Args:
        session (Session): The session of the request.
        body (bytes): The raw body: the counts, the seed and an optional economy,
            `{"counts", "seed", "economy"}`.

    Returns:
        tuple[int, dict[str, object]]: 201 and the new manifest, or 200 and the
            stored one.

    Raises:
        InputError: If a count, the seed or the economy breaks a rule.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> counts = dict.fromkeys(["materials", "components", "products"], 1)
        >>> counts |= dict.fromkeys(["suppliers", "customers", "lines"], 1)
        >>> body = write_json({"counts": counts, "seed": 0})
        >>> generate_manifest(session, body)[0]
        201
    """
    request = validate(ManifestGenerate, read_json_bytes(body))
    generated = engine.generate_manifest(
        request.counts.model_dump(), request.seed, request.economy
    )
    return create_manifest(session, write_json(generated))


def stored_manifest(session: Session, manifest_id: str) -> Manifest:
    """Give a stored manifest, or refuse an unknown one.

    Args:
        session (Session): The session of the request.
        manifest_id (str): The identifier of the manifest.

    Returns:
        Manifest: The manifest.

    Raises:
        NotFoundError: If the manifest does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = create_manifest(session, manifest_body)
        >>> stored_manifest(session, manifest["id"]).linear
        False
    """
    manifest = manifests.find_manifest(session, manifest_id)
    if manifest is None:
        raise NotFoundError(f"manifest_id: unknown manifest {manifest_id}")
    return manifest


def read_manifest(session: Session, manifest_id: str) -> dict[str, object]:
    """Read a stored manifest.

    Args:
        session (Session): The session of the request.
        manifest_id (str): The identifier of the manifest.

    Returns:
        dict[str, object]: `{"id", "content", "linear"}`.

    Raises:
        NotFoundError: If the manifest does not exist.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> manifest_body = (EXAMPLES / "manifest.json").read_bytes()
        >>> _, manifest = create_manifest(session, manifest_body)
        >>> sorted(read_manifest(session, manifest["id"]))
        ['content', 'id', 'linear']
    """
    manifest = stored_manifest(session, manifest_id)
    return {"id": manifest.id, "content": manifest.content, "linear": manifest.linear}


def list_manifests(session: Session) -> object:
    """List every stored manifest by identifier.

    Args:
        session (Session): The session of the request.

    Returns:
        object: `{"manifests": [{"id", "name", "description"}, ...]}`.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> list_manifests(session)
        {'manifests': []}
    """
    found = manifests.list_manifests(session)
    return {"manifests": [summary(*row) for row in found]}


def summary(
    stored_id: str, name: str | None, description: str | None
) -> dict[str, object]:
    """Give the identifier, name and description of a manifest or scenario in a list.

    Args:
        stored_id (str): The identifier of the manifest or scenario.
        name (str | None): Its readable name.
        description (str | None): Its readable description.

    Returns:
        dict[str, object]: `{"id", "name", "description"}`.

    Examples:
        >>> summary("m-1", "Factory", None)
        {'id': 'm-1', 'name': 'Factory', 'description': None}
    """
    return {"id": stored_id, "name": name, "description": description}
