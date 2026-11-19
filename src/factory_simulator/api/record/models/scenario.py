"""The mapped class of scenarios: a scenario stored under its manifest and its content.

Examples:
    >>> Scenario.__tablename__
    'scenarios'
"""

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factory_simulator.api.record.models.base import Base
from factory_simulator.api.record.models.manifest import Manifest


class Scenario(Base):
    """A scenario of a manifest, stored once under the identifier of both.

    Attributes:
        id (str): The SHA-256 digest, in 64 hexadecimal digits, of the canonical JSON
            of the manifest identifier and the content.
        manifest_id (str): The identifier of its manifest.
        content (object): The validated scenario with defaults written.
        manifest (Manifest): Its manifest.

    Examples:
        >>> Scenario(id="s-1", manifest_id="m-1", content={"horizon": 3}).manifest_id
        'm-1'
    """

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest_id: Mapped[str] = mapped_column(ForeignKey("manifests.id"))
    content: Mapped[object] = mapped_column(JSON)

    manifest: Mapped[Manifest] = relationship()
