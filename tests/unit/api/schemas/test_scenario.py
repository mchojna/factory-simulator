import pytest

from factory_simulator.api.core.numbers import validate
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.engine import InputError


def test_a_disruption_refuses_notice_below_0_and_a_line_breakdown_refuses_duration():
    outage = {
        "kind": "supplier_outage",
        "target": "all",
        "start": 1,
        "duration": 1,
        "strength": "0.5",
    }
    breakdown = {"kind": "line_breakdown", "target": "all", "start": 1, "loss": "0.5"}

    validate(ScenarioCreate, {"horizon": 2, "disruptions": [outage | {"notice": 1}]})
    with pytest.raises(InputError, match=r"^disruptions\.0\.notice: "):
        validate(
            ScenarioCreate, {"horizon": 2, "disruptions": [outage | {"notice": -1}]}
        )
    with pytest.raises(InputError, match=r"^disruptions\.0\.duration: "):
        validate(
            ScenarioCreate, {"horizon": 2, "disruptions": [breakdown | {"duration": 1}]}
        )
