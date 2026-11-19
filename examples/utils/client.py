"""The example HTTP inputs: the small factory and its run.

Examples:
    >>> fixture_path("manifest.json").name
    'manifest.json'
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import httpx2 as httpx

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    """Give the path of an example input fixture.

    Args:
        name (str): The fixture filename.

    Returns:
        Path: The file under `examples/utils/fixtures`.

    Examples:
        >>> fixture_path("manifest.json").name
        'manifest.json'
    """
    return FIXTURES / name


def read_fixture(name: str) -> JsonObject:
    """Read an example JSON input as an object.

    Args:
        name (str): The fixture filename.

    Returns:
        dict[str, Any]: The JSON object.

    Raises:
        ValueError: If the fixture is not a JSON object.

    Examples:
        >>> read_fixture("scenario.json")["horizon"]
        3
    """
    value = json.loads(fixture_path(name).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected a JSON object")
    return cast(JsonObject, value)


def start_example_run(
    client: httpx.Client, seed: int, scenario: JsonObject | None = None
) -> JsonObject:
    """Create the example factory, scenario and run through HTTP.

    Args:
        client (httpx.Client): The API client with the `/api/v1` base URL.
        seed (int): The deterministic seed of the run.
        scenario (dict[str, Any] | None, optional): A scenario override.

    Returns:
        dict[str, Any]: The newly started run.

    Examples:
        >>> import httpx2 as httpx
        >>> def respond(request: httpx.Request) -> httpx.Response:
        ...     if request.url.path.endswith("/manifests"):
        ...         return httpx.Response(201, text='{"id":"m-1"}')
        ...     if request.url.path.endswith("/scenarios"):
        ...         return httpx.Response(201, text='{"id":"s-1"}')
        ...     return httpx.Response(201, text='{"id":"r-1","scenario_id":"s-1"}')
        >>> transport = httpx.MockTransport(respond)
        >>> client = httpx.Client(transport=transport, base_url="http://server/api/v1")
        >>> start_example_run(client, 7)["id"]
        'r-1'
        >>> client.close()
    """
    manifest = benchmark.send(
        client, "POST", "/manifests", read_fixture("manifest.json")
    )
    scenario_body = scenario if scenario is not None else read_fixture("scenario.json")
    created_scenario = benchmark.send(
        client,
        "POST",
        f"/manifests/{manifest['id']}/scenarios",
        scenario_body,
    )
    return benchmark.start_run(client, str(created_scenario["id"]), seed)


def scenario_with_product_stock(quantity: str) -> JsonObject:
    """Give the example scenario with the requested opening product stock.

    Args:
        quantity (str): The starting quantity of monitors.

    Returns:
        dict[str, Any]: A fresh scenario body.

    Examples:
        >>> scenario_with_product_stock("4.000")["start"]["stock"]["main"]["monitor"]
        '4.000'
    """
    scenario = deepcopy(read_fixture("scenario.json"))
    scenario["name"] = f"Three period example with {quantity} monitors"
    scenario["start"]["stock"]["main"]["monitor"] = quantity
    return scenario
