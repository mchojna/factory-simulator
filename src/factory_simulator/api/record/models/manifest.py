"""The mapped class of manifests: a manifest stored under the identifier of its content.

Examples:
    >>> Manifest.__tablename__
    'manifests'
"""

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from factory_simulator.api.record.models.base import Base


class Manifest(Base):
    """A manifest, stored once under the identifier of its content.

    Attributes:
        id (str): The SHA-256 digest, in 64 hexadecimal digits, of the canonical JSON
            of the content.
        content (object): The manifest as its author wrote it, without the values of
            groups and the built-in defaults.
        linear (bool): Whether the factory is linear.

    Examples:
        >>> Manifest(id="m-1", content={"name": "Factory"}, linear=True).linear
        True
    """

    __tablename__ = "manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[object] = mapped_column(JSON)
    linear: Mapped[bool] = mapped_column(Boolean)
