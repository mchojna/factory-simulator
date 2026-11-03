from typing import Any

import pytest
from factories import (
    MANIFEST_EXAMPLES,
    SCENARIO_EXAMPLES,
    Change,
    ScenarioChange,
    api_client,
    example_count,
    get,
    post,
    records,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.models.scenario import Scenario


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in MANIFEST_EXAMPLES],
    ids=[name for name, _, _ in MANIFEST_EXAMPLES],
)
def test_an_invalid_manifest_is_answered_422_with_its_message_and_not_stored(
    change: Change, message: str
):
    manifest = tiny_manifest()
    change(manifest)
    with api_client() as client:
        response = client.post("/api/v1/manifests", content=write_json(manifest))
        stored = records(client, Manifest)

    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert stored == []


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in SCENARIO_EXAMPLES],
    ids=[name for name, _, _ in SCENARIO_EXAMPLES],
)
def test_an_invalid_scenario_is_answered_422_with_its_message_and_not_stored(
    change: ScenarioChange, message: str
):
    manifest, scenario = tiny_manifest(), tiny_scenario()
    change(manifest, scenario)
    with api_client() as client:
        _, created = post(client, "/manifests", manifest)
        response = client.post(
            f"/api/v1/manifests/{created['id']}/scenarios",
            content=write_json(scenario),
        )
        stored = records(client, Scenario)

    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert stored == []


def test_a_duplicate_key_is_answered_422_with_its_message():
    text = write_json(tiny_manifest()).decode()
    start = text.index('"chip":{')
    chip = text[start : text.index("}", start) + 1]
    with api_client() as client:
        response = client.post(
            "/api/v1/manifests", content=text.replace(chip, chip + "," + chip, 1)
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "materials.chip: duplicate key"


def test_a_duplicate_key_of_a_scenario_is_answered_422_with_its_message():
    text = write_json(tiny_scenario()).decode()
    with api_client() as client:
        _, created = post(client, "/manifests", tiny_manifest())
        response = client.post(
            f"/api/v1/manifests/{created['id']}/scenarios",
            content=text.replace('"horizon":5', '"horizon":5,"horizon":5', 1),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "horizon: duplicate key"


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories())
def test_a_stored_manifest_reads_back_as_the_same_model(
    factory: tuple[dict[str, Any], dict[str, Any]],
):
    with api_client() as client:
        status, created = post(client, "/manifests", factory[0])
        _, read = get(client, f"/manifests/{created['id']}")
        _, again = post(client, "/manifests", read["content"])

    assert status == 201
    assert read == created
    assert again == created
    content = created["content"]
    for kind in ("components", "products"):
        for item in content[kind].values():
            assert item["default_recipe"] in item["recipes"]
