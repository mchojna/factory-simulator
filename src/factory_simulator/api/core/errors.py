"""The errors of a request: not found, answered 404, and conflict, answered 409.

Examples:
    >>> str(NotFoundError("run_id: unknown run r-1"))
    'run_id: unknown run r-1'
"""

from factory_simulator.api.core.numbers import StrictModel


class NotFoundError(Exception):
    """A manifest, scenario or run that does not exist; answered 404.

    Examples:
        >>> str(NotFoundError("run_id: unknown run r-1"))
        'run_id: unknown run r-1'
    """


class ConflictError(Exception):
    """A request that conflicts with the state of a run; answered 409.

    Examples:
        >>> str(ConflictError("run: the run is finished"))
        'run: the run is finished'
    """


class ErrorPublic(StrictModel):
    """The body of every error answer: the path of the problem and the problem.

    Attributes:
        detail (str): `<path>: <problem>`.

    Examples:
        >>> ErrorPublic(detail="run_id: unknown run r-1").detail
        'run_id: unknown run r-1'
    """

    detail: str
