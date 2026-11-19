import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    Client,
    Schema,
    api_client,
    example_count,
    get,
    post,
    records,
    schema_errors,
    small_factories,
    statements_of,
    threaded_api_client,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.services.examples import EXAMPLES


# The OpenAPI schemas of the body of `POST /manifests` and of the answer of
# `GET /manifests/{manifest_id}`, and the schemas they reference.
def manifest_schemas(client: Client) -> tuple[Schema, Schema, Schema]:
    _, document = get(client, "/openapi.json")
    paths = document["paths"]
    body = paths["/api/v1/manifests"]["post"]["requestBody"]
    answer = paths["/api/v1/manifests/{manifest_id}"]["get"]["responses"]["200"]
    return (
        body["content"]["application/json"]["schema"],
        answer["content"]["application/json"]["schema"],
        document["components"]["schemas"],
    )


def test_a_manifest_sent_twice_gets_one_identifier_from_its_content():
    with api_client() as client:
        first_status, first = post(client, "/manifests", tiny_manifest())
        second_status, second = post(client, "/manifests", tiny_manifest())

    assert (first_status, second_status) == (201, 200)
    assert first == second
    assert first["id"] == hashlib.sha256(write_json(first["content"])).hexdigest()
    assert first["linear"] is True
    assert first["content"]["materials"]["chip"]["space"] == Decimal("0.01")


def test_two_identical_manifests_sent_at_once_give_201_and_200():
    with threaded_api_client() as client, ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(post, client, "/manifests", tiny_manifest())
            for _ in range(2)
        ]
        answers = [future.result() for future in futures]
        rows = records(client, Manifest)

    assert sorted(status for status, _ in answers) == [200, 201]
    assert answers[0][1]["id"] == answers[1][1]["id"]
    assert len(rows) == 1


def test_a_name_that_is_not_valid_unicode_is_refused_at_its_key():
    body = write_json(tiny_manifest() | {"name": "NAME"}).replace(b"NAME", b"\\ud800")
    with api_client() as client:
        response = client.post("/api/v1/manifests", content=body)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "name: is not valid text"},
    )


def test_the_example_manifest_and_its_answer_follow_their_openapi_schemas():
    manifest = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    with api_client() as client:
        body_schema, answer_schema, definitions = manifest_schemas(client)
        _, created = post(client, "/manifests", manifest)
        _, answer = get(client, f"/manifests/{created['id']}")

    assert schema_errors(manifest, body_schema, definitions) == []
    assert schema_errors(answer, answer_schema, definitions) == []


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories())
def test_every_accepted_manifest_and_its_answer_follow_their_openapi_schemas(
    factory: tuple[dict[str, Any], dict[str, Any]],
):
    manifest, _ = factory
    with api_client() as client:
        body_schema, answer_schema, definitions = manifest_schemas(client)
        status, created = post(client, "/manifests", manifest)
        _, answer = get(client, f"/manifests/{created['id']}")

    assert status == 201
    assert schema_errors(manifest, body_schema, definitions) == []
    assert schema_errors(answer, answer_schema, definitions) == []


def test_the_lists_of_manifests_and_scenarios_read_no_whole_content():
    name = 'Za\u017c\u00f3\u0142\u0107 "w" \\ \n'
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest() | {"name": name})
        path = f"/manifests/{manifest['id']}/scenarios"
        _, scenario = post(client, path, tiny_scenario() | {"description": name})
        answers: list[object] = []
        manifest_statements = statements_of(
            client, lambda: answers.append(get(client, "/manifests"))
        )
        scenario_statements = statements_of(
            client, lambda: answers.append(get(client, path))
        )

    whole_manifest = re.compile(r"\bmanifests\.content\b(?! ->>)")
    whole_scenario = re.compile(r"\bscenarios\.content\b(?! ->>)")
    assert [text for text in manifest_statements if whole_manifest.search(text)] == []
    assert [text for text in scenario_statements if whole_scenario.search(text)] == []
    assert answers == [
        (
            200,
            {"manifests": [{"id": manifest["id"], "name": name, "description": None}]},
        ),
        (
            200,
            {
                "scenarios": [
                    {"id": scenario["id"], "name": "Tiny scenario", "description": name}
                ]
            },
        ),
    ]
