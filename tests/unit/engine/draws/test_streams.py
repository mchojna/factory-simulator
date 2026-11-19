from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    FactoryBodies,
    draw_world_of_bodies,
    seeds,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import assume, given
from hypothesis import strategies as st

LOGNORMAL_SHARE = {
    "min": "0.5000",
    "max": "1.0000",
    "distribution": "lognormal",
    "median": "0.9000",
    "spread": "0.2000",
}


def completeness_draws(delay: object) -> list[Decimal]:
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["delay"] = delay
    entry["completeness"] = {"min": "0.9000", "max": "1.0000"}
    world = draw_world_of_bodies(manifest, tiny_scenario(), seed=4)
    return [delivery.completeness for delivery in world.deliveries["chip-maker/chip"]]


def changed_slot(value: object, key: str, lognormal: bool) -> object:
    if lognormal and key != "delay":
        return LOGNORMAL_SHARE
    if not isinstance(value, dict):
        if key == "delay":
            return {"min": int(str(value)), "max": int(str(value)) + 1}
        return {"min": "0.0000", "max": "1.0000"}
    written = cast(dict[str, Any], value)
    if key == "delay":
        return written | {"max": int(written["max"]) + 1}
    if written.get("distribution") == "triangular" or written["min"] == written["max"]:
        return {
            "min": "0.0000",
            "max": "1.0000",
            "distribution": "triangular",
            "mode": "0.5000",
        }
    bounds = {"min": written["min"], "max": written["max"]}
    return bounds | {"distribution": "triangular", "mode": written["min"]}


def test_a_fixed_parameter_takes_its_slot_of_the_stream():
    assert completeness_draws(1) == completeness_draws({"min": 1, "max": 2})


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_changing_one_slot_of_a_stream_leaves_every_other_draw(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    supplier = data.draw(st.sampled_from(sorted(manifest["suppliers"])))
    entries = manifest["suppliers"][supplier]["catalogue"]
    material = data.draw(st.sampled_from(sorted(entries)))
    key = data.draw(st.sampled_from(["delay", "completeness", "acceptance"]))
    entry = entries[material]
    assume(key in entry)
    entry[key] = changed_slot(entry[key], key, data.draw(st.booleans()))
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    path = f"suppliers.{supplier}.catalogue.{material}.{key}"
    assert {key: value for key, value in after.parameters.items() if key != path} == {
        key: value for key, value in before.parameters.items() if key != path
    }
    others = [
        name
        for name in ("punctual", "delay", "completeness", "acceptance")
        if name != key
    ]
    for pair, deliveries in before.deliveries.items():
        for first, second in zip(deliveries, after.deliveries[pair], strict=True):
            for name in others:
                assert getattr(first, name) == getattr(second, name)
    assert before.breakdowns == after.breakdowns
    assert before.demand == after.demand
