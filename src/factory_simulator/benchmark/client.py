"""The client of the benchmark: the calls to the HTTP interface that play a run.

Examples:
    >>> import httpx2 as httpx
    >>> transport = httpx.MockTransport(lambda request: httpx.Response(200, text="{}"))
    >>> read(httpx.Client(transport=transport, base_url="http://server"), "/runs/r")
    {}
"""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import httpx2 as httpx

type JsonObject = dict[str, Any]
type Agent = Callable[[JsonObject, JsonObject], list[JsonObject]]
"""An agent: a function of the description of a run and the observation of a period
that gives the decisions of the period. The description is read-only."""
type Check = Callable[[int, list[JsonObject]], list[JsonObject]]
"""A check: a function of a period and its decisions that gives the outcome of every
decision; the run stays as it is."""


def send(client: httpx.Client, method: str, path: str, body: object) -> JsonObject:
    """Send a body to a route and read its answer.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        method (str): The method, such as `POST`.
        path (str): The path of the route, such as `/runs`.
        body (object): The body; a `Decimal` goes as its text.

    Returns:
        dict[str, Any]: The answer, each number with a fraction a `Decimal`.

    Raises:
        RuntimeError: If the status of the answer is 400 or more, or its body is not
            a JSON object.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(201, content=request.content)
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> send(client, "POST", "/runs", {"seed": Decimal("7")})
        {'seed': '7'}
    """
    content = json.dumps(body, default=str)
    answer = client.request(method, path, content=content)
    return answer_of(answer, method, path)


def read(client: httpx.Client, path: str) -> JsonObject:
    """Read a route.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        path (str): The path of the route, such as `/manifests`.

    Returns:
        dict[str, Any]: The answer, each number with a fraction a `Decimal`.

    Raises:
        RuntimeError: If the status of the answer is 400 or more, or its body is not
            a JSON object.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"period": 2}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> read(client, "/runs/r")
        {'period': 2}
    """
    return answer_of(client.get(path), "GET", path)


def answer_of(answer: httpx.Response, method: str, path: str) -> JsonObject:
    """Give the body of an answer, or refuse it when its status is 400 or more.

    A refused answer names its `detail` when its body is a JSON object with that key,
    else the text of its body.

    Args:
        answer (httpx.Response): The answer.
        method (str): The method of the request.
        path (str): The path of the request.

    Returns:
        dict[str, Any]: The answer, each number with a fraction a `Decimal`.

    Raises:
        RuntimeError: If the status of the answer is 400 or more, or its body is not
            a JSON object.

    Examples:
        >>> import httpx2 as httpx
        >>> answer_of(httpx.Response(200, text='{"cash": 1.25}'), "GET", "/x")
        {'cash': Decimal('1.25')}
    """
    status = answer.status_code
    if status >= 400:
        raise RuntimeError(f"{method} {path}: {status} {detail_of(answer)}")
    try:
        read_answer = json.loads(answer.text, parse_float=Decimal)
    except json.JSONDecodeError:
        read_answer = None
    if not isinstance(read_answer, dict):
        raise RuntimeError(f"{method} {path}: {status} not a JSON object")
    return cast(JsonObject, read_answer)


def detail_of(answer: httpx.Response) -> str:
    """Give the detail of a refused answer: its `detail`, or else its text.

    Args:
        answer (httpx.Response): The answer, its status 400 or more.

    Returns:
        str: The `detail` of a body that is a JSON object with that key, else the
            text of the body.

    Examples:
        >>> import httpx2 as httpx
        >>> detail_of(httpx.Response(409, text='{"detail": "run: finished"}'))
        'run: finished'
        >>> detail_of(httpx.Response(500, text="Internal Server Error"))
        'Internal Server Error'
    """
    try:
        body = json.loads(answer.text)
    except json.JSONDecodeError:
        return answer.text
    if isinstance(body, dict) and "detail" in body:
        return str(cast(JsonObject, body)["detail"])
    return answer.text


def find_manifest(client: httpx.Client, name: str) -> str:
    """Find the identifier of a stored manifest by its name.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        name (str): The `name` of the manifest.

    Returns:
        str: The identifier of the manifest.

    Raises:
        ValueError: If no stored manifest has the name.

    Examples:
        >>> import httpx2 as httpx
        >>> body = '{"manifests": [{"id": "m1", "name": "Tiny factory"}]}'
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text=body)
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> find_manifest(client, "Tiny factory")
        'm1'
    """
    for manifest in read(client, "/manifests")["manifests"]:
        if manifest["name"] == name:
            return str(manifest["id"])
    raise ValueError(f"name: no stored manifest is named {name}")


def find_scenario(client: httpx.Client, manifest_id: str, name: str) -> str:
    """Find the identifier of a stored scenario of a manifest by its name.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        manifest_id (str): The identifier of the manifest.
        name (str): The `name` of the scenario.

    Returns:
        str: The identifier of the scenario.

    Raises:
        ValueError: If no scenario of the manifest has the name.

    Examples:
        >>> import httpx2 as httpx
        >>> body = '{"scenarios": [{"id": "s1", "name": "Tiny scenario"}]}'
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text=body)
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> find_scenario(client, "m1", "Tiny scenario")
        's1'
    """
    for scenario in read(client, f"/manifests/{manifest_id}/scenarios")["scenarios"]:
        if scenario["name"] == name:
            return str(scenario["id"])
    raise ValueError(f"name: no scenario of the manifest is named {name}")


def start_run(client: httpx.Client, scenario_id: str, seed: int) -> JsonObject:
    """Start a run of a scenario with a seed.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        scenario_id (str): The identifier of the scenario.
        seed (int): The seed of the run.

    Returns:
        dict[str, Any]: The run: `id`, `scenario_id`, `description`, `period`,
            `finished`.

    Raises:
        RuntimeError: If the HTTP interface refuses the run.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(201, text='{"id": "r1", "period": 1}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> start_run(client, "s1", 0)["id"]
        'r1'
    """
    return send(client, "POST", "/runs", {"scenario_id": scenario_id, "seed": seed})


def create_shown_description(
    client: httpx.Client, manifest_id: str, seed: int, scenario_content: JsonObject
) -> JsonObject:
    """Create a twin of a scenario with nothing hidden and a run; give its description.

    The twin is the content with `hidden` empty and, when it has a `name`, the name
    `<name>-shown`. A run of the twin is started with the seed and never played. Its
    description shows every parameter group as a range with its `cut_mean`, never a
    value drawn for a period.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        manifest_id (str): The identifier of the manifest of the scenario.
        seed (int): The seed of the run the description is for.
        scenario_content (dict[str, Any]): The content of the scenario as its harness
            sent it.

    Returns:
        dict[str, Any]: The description of the run of the twin.

    Raises:
        RuntimeError: If the HTTP interface refuses the twin or its run.

    Examples:
        >>> import httpx2 as httpx
        >>> def handle(request: httpx.Request) -> httpx.Response:
        ...     if request.url.path.endswith("/scenarios"):
        ...         return httpx.Response(201, text='{"id": "s2"}')
        ...     return httpx.Response(201, text='{"id": "r1", "description": {}}')
        >>> client = httpx.Client(
        ...     transport=httpx.MockTransport(handle), base_url="http://server"
        ... )
        >>> create_shown_description(client, "m1", 0, {"horizon": 3})
        {}
    """
    twin = dict(scenario_content)
    twin["hidden"] = []
    if "name" in scenario_content:
        twin["name"] = f"{scenario_content['name']}-shown"
    scenario = send(client, "POST", f"/manifests/{manifest_id}/scenarios", twin)
    return start_run(client, scenario["id"], seed)["description"]


def play_run(client: httpx.Client, run: JsonObject, agent: Agent) -> JsonObject:
    """Play a started run to its end with an agent and give its result.

    In every period the agent reads the description of the run and the observation,
    and its decisions are submitted for the period of the observation.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        run (dict[str, Any]): The run as `start_run` gives it.
        agent (Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]): The
            function that decides each period.

    Returns:
        dict[str, Any]: The result of the run, from `GET /runs/{id}/result`.

    Raises:
        RuntimeError: If the HTTP interface refuses a request.

    Examples:
        >>> import httpx2 as httpx
        >>> def handle(request: httpx.Request) -> httpx.Response:
        ...     if request.url.path.endswith("/observation"):
        ...         return httpx.Response(200, text='{"period": 1}')
        ...     if request.url.path.endswith("/decisions"):
        ...         return httpx.Response(200, text='{"finished": true}')
        ...     return httpx.Response(200, text='{"profit": 0}')
        >>> client = httpx.Client(
        ...     transport=httpx.MockTransport(handle), base_url="http://server"
        ... )
        >>> run = {"id": "r1", "description": {}}
        >>> play_run(client, run, lambda description, observation: [])
        {'profit': 0}
    """
    run_id = run["id"]
    observation = read(client, f"/runs/{run_id}/observation")
    while True:
        decisions = agent(run["description"], observation)
        body = {"period": observation["period"], "decisions": decisions}
        answer = send(client, "POST", f"/runs/{run_id}/decisions", body)
        if answer.get("finished") is True:
            return read(client, f"/runs/{run_id}/result")
        observation = answer


def create_check(
    client: httpx.Client, run_id: str, period: int, decisions: list[JsonObject]
) -> list[JsonObject]:
    """Create a check of decisions of a period, as their execution would check them.

    The run stays as it is; the HTTP interface keeps the check among its interactions.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        run_id (str): The identifier of the run.
        period (int): The current period of the run.
        decisions (list[dict[str, Any]]): The decisions.

    Returns:
        list[dict[str, Any]]: The outcome of every decision, in execution order.

    Raises:
        RuntimeError: If the HTTP interface refuses the check.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"outcomes": []}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> create_check(client, "r1", 1, [])
        []
    """
    body = {"period": period, "decisions": decisions}
    return send(client, "POST", f"/runs/{run_id}/checks", body)["outcomes"]


def read_world(client: httpx.Client, run_id: str) -> JsonObject:
    """Read the world of a finished run.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        run_id (str): The identifier of the run.

    Returns:
        dict[str, Any]: The world, from `GET /runs/{id}/world`.

    Raises:
        RuntimeError: If the run is not finished.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"yields": {}}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> read_world(client, "r1")
        {'yields': {}}
    """
    return read(client, f"/runs/{run_id}/world")


def read_periods(client: httpx.Client, run_id: str) -> list[JsonObject]:
    """Read every closed period of a run.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        run_id (str): The identifier of the run.

    Returns:
        list[dict[str, Any]]: The periods of `GET /runs/{id}/periods`.

    Raises:
        RuntimeError: If the HTTP interface refuses the request.

    Examples:
        >>> import httpx2 as httpx
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"periods": []}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> read_periods(client, "r1")
        []
    """
    return read(client, f"/runs/{run_id}/periods")["periods"]
