import hashlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from factories import (
    api_client,
    get,
    post,
    records,
    threaded_api_client,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.scenario import Scenario


def test_one_scenario_under_two_manifests_gets_two_identifiers():
    other = tiny_manifest()
    other["name"] = "Other factory"
    with api_client() as client:
        _, first = post(client, "/manifests", tiny_manifest())
        _, second = post(client, "/manifests", other)
        first_status, under_first = post(
            client, f"/manifests/{first['id']}/scenarios", tiny_scenario()
        )
        again_status, again = post(
            client, f"/manifests/{first['id']}/scenarios", tiny_scenario()
        )
        _, under_second = post(
            client, f"/manifests/{second['id']}/scenarios", tiny_scenario()
        )

    assert (first_status, again_status) == (201, 200)
    assert again == under_first
    assert under_first["id"] != under_second["id"]
    expected = {"manifest_id": first["id"], "scenario": under_first["content"]}
    assert under_first["id"] == hashlib.sha256(write_json(expected)).hexdigest()
    assert under_first["content"]["start"]["cash"] == Decimal("1000")


def test_manifests_and_scenarios_can_be_listed_and_read():
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest())
        _, scenario = post(
            client, f"/manifests/{manifest['id']}/scenarios", tiny_scenario()
        )
        listed = get(client, "/manifests")
        read = get(client, f"/manifests/{manifest['id']}")
        scenarios = get(client, f"/manifests/{manifest['id']}/scenarios")
        read_scenario = get(client, f"/scenarios/{scenario['id']}")

    assert listed == (
        200,
        {
            "manifests": [
                {"id": manifest["id"], "name": "Tiny factory", "description": None}
            ]
        },
    )
    assert read == (200, manifest)
    assert scenarios == (
        200,
        {
            "scenarios": [
                {"id": scenario["id"], "name": "Tiny scenario", "description": None}
            ]
        },
    )
    assert read_scenario == (200, scenario)


def test_unknown_manifest_and_scenario_answer_404_with_their_text():
    with api_client() as client:
        manifest = get(client, "/manifests/abc")
        scenario = get(client, "/scenarios/xyz")
        scenario_of_unknown = post(client, "/manifests/abc/scenarios", tiny_scenario())

    assert manifest == (404, {"detail": "manifest_id: unknown manifest abc"})
    assert scenario == (404, {"detail": "scenario_id: unknown scenario xyz"})
    assert scenario_of_unknown == (404, {"detail": "manifest_id: unknown manifest abc"})


def test_two_identical_scenarios_sent_at_once_give_201_and_200():
    with threaded_api_client() as client, ThreadPoolExecutor(max_workers=2) as executor:
        _, manifest = post(client, "/manifests", tiny_manifest())
        path = f"/manifests/{manifest['id']}/scenarios"
        futures = [
            executor.submit(post, client, path, tiny_scenario()) for _ in range(2)
        ]
        answers = [future.result() for future in futures]
        rows = records(client, Scenario)

    assert sorted(status for status, _ in answers) == [200, 201]
    assert answers[0][1]["id"] == answers[1][1]["id"]
    assert len(rows) == 1


def test_a_scenario_whose_space_can_exceed_the_record_is_refused():
    manifest = tiny_manifest()
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item["space"] = 10**24
    manifest["warehouses"]["main"]["capacity"] = 1000 * 10**24
    with api_client() as client:
        _, created = post(client, "/manifests", manifest)
        answer = post(client, f"/manifests/{created['id']}/scenarios", tiny_scenario())

    assert answer == (
        422,
        {
            "detail": "horizon: a run of this scenario can exceed the numbers the "
            "record holds"
        },
    )
