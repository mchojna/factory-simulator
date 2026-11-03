from typing import Any, cast

from factories import random_world

from factory_simulator.api.services.writers.world import world_json


def test_a_disruption_is_visible_from_period_1_at_the_earliest():
    disruptions = cast(dict[str, Any], world_json(random_world(2)))["disruptions"]

    assert [disruption["visible"] for disruption in disruptions] == [1, 1, 1, 2, 3, 4]
