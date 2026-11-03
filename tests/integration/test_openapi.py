import re
from importlib import metadata
from typing import Any

from factories import (
    api_client,
    get,
)

from factory_simulator.api.core.json import write_json

ERROR_STATUSES = {
    ("/api/v1/manifests", "get"): {"503"},
    ("/api/v1/manifests", "post"): {"422", "503"},
    ("/api/v1/manifests/generated", "post"): {"422", "503"},
    ("/api/v1/manifests/{manifest_id}", "get"): {"404", "503"},
    ("/api/v1/manifests/{manifest_id}/scenarios", "post"): {"404", "422", "503"},
    ("/api/v1/manifests/{manifest_id}/scenarios", "get"): {"404", "503"},
    ("/api/v1/scenarios/{scenario_id}", "get"): {"404", "503"},
    ("/api/v1/runs", "post"): {"404", "422", "503"},
    ("/api/v1/runs/{run_id}", "get"): {"404", "409", "503"},
    ("/api/v1/runs/{run_id}/observation", "get"): {"404", "409", "503"},
    ("/api/v1/runs/{run_id}/decisions", "post"): {"404", "409", "422", "503"},
    ("/api/v1/runs/{run_id}/checks", "post"): {"404", "409", "422", "503"},
    ("/api/v1/runs/{run_id}/forks", "post"): {"404", "409", "422", "503"},
    ("/api/v1/runs/{run_id}/periods", "get"): {"404", "409", "503"},
    ("/api/v1/runs/{run_id}/result", "get"): {"404", "409", "503"},
    ("/api/v1/runs/{run_id}/world", "get"): {"404", "409", "503"},
    ("/api/v1/runs/{run_id}/export", "get"): {"404", "409", "503"},
}


def operations(schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (path, operation)
        for path, methods in schema["paths"].items()
        for operation in methods.values()
    ]


def test_openapi_holds_the_body_schemas_with_numbers():
    with api_client() as client:
        status, schema = get(client, "/openapi.json")

    assert status == 200
    components = schema["components"]["schemas"]
    for name in ["ManifestCreate", "ScenarioCreate", "RunCreate", "DecisionsCreate"]:
        assert name in components
    assert components["ShipCreate"]["properties"]["quantity"]["anyOf"] == [
        {"type": "number"},
        {"type": "string", "pattern": "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$"},
    ]
    assert components["RunCreate"]["properties"]["seed"]["anyOf"] == [
        {"type": "integer"},
        {"type": "string", "pattern": "^-?(0|[1-9][0-9]*)$"},
    ]
    assert components["ResultPublic"]["properties"]["profit"]["type"] == "number"
    assert components["ResultPublic"]["properties"]["seed"]["type"] == "integer"
    responses = schema["paths"]["/api/v1/manifests"]["post"]["responses"]
    assert {"200", "201"} <= set(responses)


def test_the_openapi_schema_defines_every_schema_it_references():
    with api_client() as client:
        _, schema = get(client, "/openapi.json")

    references = set(
        re.findall(r'"#/components/schemas/([^"]+)"', write_json(schema).decode())
    )
    assert references <= set(schema["components"]["schemas"])


def test_the_openapi_schema_gives_the_version_of_the_package():
    with api_client() as client:
        _, schema = get(client, "/openapi.json")

    assert schema["info"]["version"] == metadata.version("factory-simulator")


def test_no_operation_shows_dependencies_or_python_names():
    with api_client() as client:
        _, schema = get(client, "/openapi.json")

    hidden = ["Session", "Server", "NotFoundError", "ConflictError", "InputError"]
    found = [
        (path, word)
        for path, operation in operations(schema)
        for word in [*hidden, ">>>"]
        if word in operation.get("description", "")
    ]
    assert found == []


def test_every_operation_declares_its_error_statuses_with_one_error_body():
    with api_client() as client:
        _, schema = get(client, "/openapi.json")

    declared = {
        (path, method): {
            status for status in operation["responses"] if int(status) >= 400
        }
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    }
    bodies = {
        operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        for methods in schema["paths"].values()
        for operation in methods.values()
        for status in operation["responses"]
        if int(status) >= 400
    }
    assert declared == ERROR_STATUSES
    assert bodies == {"#/components/schemas/ErrorPublic"}
    assert "HTTPValidationError" not in write_json(schema).decode()
