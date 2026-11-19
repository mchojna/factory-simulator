"""The writer of an observation: the observation of a period as JSON, hidden values out.

Examples:
    >>> observation_json(None, ()) is None
    True
"""

from typing import cast

from factory_simulator import engine
from factory_simulator.api.services.readers.scenario import EFFECT_KEYS
from factory_simulator.api.services.writers.values import plain


def seen_disruption_json(disruption: engine.Disruption) -> dict[str, object]:
    """Write a disruption whose target is expanded, as the observation shows it.

    Args:
        disruption (Disruption): The disruption, its target a tuple of identifiers.

    Returns:
        dict[str, object]: Its `id`, `kind`, `target` as a list, `start`, `duration`
            except for a line breakdown, and its effect key.

    Examples:
        >>> from decimal import Decimal
        >>> delay = engine.Disruption(
        ...     id="disruption-1",
        ...     kind="transport_delay",
        ...     target=("apac-chips",),
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal("2"),
        ... )
        >>> seen_disruption_json(delay)["delay"]
        2
    """
    written: dict[str, object] = {
        "id": disruption.id,
        "kind": disruption.kind,
        "target": list(disruption.target or ()),
        "start": disruption.start,
    }
    if disruption.kind != "line_breakdown":
        written["duration"] = disruption.duration
    effect = disruption.effect
    key = EFFECT_KEYS[disruption.kind]
    written[key] = int(effect) if key == "delay" else effect
    return written


def observation_json(
    observation: engine.Observation | None, hidden: tuple[str, ...]
) -> object:
    """Write an observation, each disruption with its effect under its own key.

    Args:
        observation (Observation | None): The observation; None before
            `build_observation`.
        hidden (tuple[str, ...]): The hidden parameter groups; with
            `disruptions.duration` no disruption shows its duration.

    Returns:
        object: The fields of the observation, or None.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes, validate
        >>> from factory_simulator.api.schemas.scenario import ScenarioCreate
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.readers.manifest import read_factory
        >>> from factory_simulator.api.services.readers.scenario import to_scenario
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> factory = read_factory(content)
        >>> scenario = to_scenario(validate(ScenarioCreate, {"horizon": 3}))
        >>> world = engine.draw_world(factory, scenario, 1)
        >>> state = engine.start_period(engine.build_state(world), world)
        >>> observation_json(state.observation, ())["period"]
        1
    """
    if observation is None:
        return None
    written = cast(dict[str, object], plain(observation))
    seen = [seen_disruption_json(disruption) for disruption in observation.disruptions]
    if "disruptions.duration" in hidden:
        for disruption in seen:
            disruption.pop("duration", None)
    written["disruptions"] = seen
    return written
