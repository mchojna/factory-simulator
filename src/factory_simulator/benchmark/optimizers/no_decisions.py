"""The agent of no decisions: an agent that decides nothing in any period.

Examples:
    >>> no_decisions({}, {})
    []
"""

from factory_simulator.benchmark.client import JsonObject


def no_decisions(description: JsonObject, observation: JsonObject) -> list[JsonObject]:  # noqa: ARG001
    """Give no decisions for a period, whatever the run and its observation.

    Args:
        description (dict[str, Any]): The description of the run.
        observation (dict[str, Any]): The observation of the period.

    Returns:
        list[dict[str, Any]]: An empty list.

    Examples:
        >>> no_decisions({}, {})
        []
    """
    return []
