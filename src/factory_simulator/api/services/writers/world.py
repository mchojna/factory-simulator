"""The writer of a world: the world of a run as JSON in the shape of the record.

Examples:
    >>> from decimal import Decimal
    >>> world = engine.draw_world(
    ...     engine.Factory(
    ...         materials={},
    ...         components={},
    ...         products={},
    ...         suppliers={},
    ...         customers={},
    ...         lines={},
    ...         warehouses={},
    ...         cash=engine.Cash(
    ...             credit_limit=Decimal(0),
    ...             credit_interest=Decimal(0),
    ...             debit_interest=Decimal(0),
    ...             overdraft_interest=Decimal(0),
    ...         ),
    ...     ),
    ...     engine.Scenario(horizon=4),
    ...     seed=0,
    ... )
    >>> world_json(world)["disruptions"]
    []
"""

from dataclasses import replace

from factory_simulator import engine
from factory_simulator.api.services.writers.observation import seen_disruption_json
from factory_simulator.api.services.writers.values import plain


def world_json(world: engine.World) -> dict[str, object]:
    """Write the world of a run in the shape of the record.

    Args:
        world (World): The world.

    Returns:
        dict[str, object]: Its parameters, demand, forecasts and their errors,
            deliveries, yields, breakdowns and disruptions, then the prices drawn
            once per period and the deliveries of express orders when there are
            any.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes, validate
        >>> from factory_simulator.api.schemas.scenario import ScenarioCreate
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.readers.manifest import read_factory
        >>> from factory_simulator.api.services.readers.scenario import to_scenario
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> factory = read_factory(content)
        >>> scenario = to_scenario(validate(ScenarioCreate, {"horizon": 3}))
        >>> world = world_json(engine.draw_world(factory, scenario, 1))
        >>> world["disruptions"]
        []
    """
    written: dict[str, object] = {
        "parameters": {
            path: {
                "value": value,
                "origin": world.factory.origins.get(path, "default"),
                "drawn": path in world.drawn,
            }
            for path, value in world.parameters.items()
        },
        "demand": plain(world.demand),
        "forecasts": plain(world.forecasts),
        "forecast_errors": plain(world.forecast_errors),
        "deliveries": plain(world.deliveries),
        "yields": plain(world.yields),
        "breakdowns": plain(world.breakdowns),
        "disruptions": [
            disruption_json(disruption, world) for disruption in world.disruptions
        ],
    }
    if world.prices:
        written["prices"] = plain(world.prices)
    if world.express_deliveries:
        written["express_deliveries"] = plain(world.express_deliveries)
    return written


def disruption_json(
    disruption: engine.Disruption, world: engine.World
) -> dict[str, object]:
    """Write a disruption of the world.

    Args:
        disruption (Disruption): The disruption.
        world (World): The world, which expands a target of `all`.

    Returns:
        dict[str, object]: Its `id`, `kind`, `target` as a sorted list, `start`,
            `duration` except for a line breakdown, its effect key and `visible`, the
            first period it is visible, at least 1.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes, validate
        >>> from factory_simulator.api.schemas.scenario import ScenarioCreate
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.readers.manifest import read_factory
        >>> from factory_simulator.api.services.readers.scenario import to_scenario
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> factory = read_factory(content)
        >>> outage = {
        ...     "kind": "supplier_outage",
        ...     "target": ["apac-chips"],
        ...     "start": 2,
        ...     "duration": 1,
        ...     "notice": 1,
        ...     "strength": "0.5",
        ... }
        >>> scenario = to_scenario(
        ...     validate(ScenarioCreate, {"horizon": 3, "disruptions": [outage]})
        ... )
        >>> world = engine.draw_world(factory, scenario, 1)
        >>> disruption_json(world.disruptions[0], world)["visible"]
        1
    """
    expanded = replace(
        disruption, target=engine.targets_of(disruption, world), group=None
    )
    return seen_disruption_json(expanded) | {
        "visible": max(1, disruption.start - disruption.notice)
    }
