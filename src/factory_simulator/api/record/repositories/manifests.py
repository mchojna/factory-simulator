"""The rows of manifests: add, find and list.

Examples:
    >>> from factory_simulator.api.record import database
    >>> database_engine = database.create_database_engine("duckdb:///:memory:")
    >>> database.prepare(database_engine, "0.1.0")
    >>> find_manifest(Session(database_engine), "m-1") is None
    True
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.repositories import add_once


def add_manifest(session: Session, manifest: Manifest) -> bool:
    """Add a manifest unless one with its identifier is stored.

    Args:
        session (Session): The session; the function commits.
        manifest (Manifest): The new manifest.

    Returns:
        bool: True when the manifest is new.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> add_manifest(session, Manifest(id="m-1", content={}, linear=True))
        True
    """
    return add_once(session, manifest, manifest.id)


def find_manifest(session: Session, manifest_id: str) -> Manifest | None:
    """Find a stored manifest.

    Args:
        session (Session): The session; its caller commits.
        manifest_id (str): The identifier of the manifest.

    Returns:
        Manifest | None: The manifest, or None when there is none.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> find_manifest(session, "m-1") is None
        True
    """
    return session.get(Manifest, manifest_id)


def list_manifests(session: Session) -> Sequence[tuple[str, str | None, str | None]]:
    """List the identifier, name and description of every stored manifest.

    The database reads the name and the description out of the content, so the
    content itself is never sent.

    Args:
        session (Session): The session; its caller commits.

    Returns:
        Sequence[tuple[str, str | None, str | None]]: The identifier, name and
            description of each manifest, by identifier.

    Examples:
        >>> from factory_simulator.api.record import database
        >>> database_engine = database.create_database_engine("duckdb:///:memory:")
        >>> database.prepare(database_engine, "0.1.0")
        >>> session = Session(database_engine, expire_on_commit=False)
        >>> list_manifests(session)
        []
    """
    statement = select(
        Manifest.id,
        Manifest.content["name"].as_string(),
        Manifest.content["description"].as_string(),
    ).order_by(Manifest.id)
    return session.execute(statement).all()
