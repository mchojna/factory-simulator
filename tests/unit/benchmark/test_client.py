import json
from decimal import Decimal
from typing import Any

import httpx2 as httpx
import pytest

from factory_simulator.benchmark.client import (
    answer_of,
    create_shown_description,
    find_manifest,
    read,
    send,
)


def client_of(answer: httpx.Response, sent: list[bytes]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return answer

    return httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://server/api/v1"
    )


def test_a_decimal_is_sent_as_its_text():
    sent: list[bytes] = []
    client = client_of(httpx.Response(200, json={}), sent)

    send(client, "POST", "/runs", {"quantity": Decimal("4.000")})

    assert json.loads(sent[0]) == {"quantity": "4.000"}


def test_a_number_of_an_answer_is_read_as_a_decimal():
    client = client_of(httpx.Response(200, text='{"profit": 328.4}'), [])

    assert read(client, "/runs/r/result") == {"profit": Decimal("328.4")}


def test_a_refused_request_raises_with_its_method_path_status_and_detail():
    answer = httpx.Response(409, json={"detail": "run: the run is finished"})
    client = client_of(answer, [])

    with pytest.raises(RuntimeError) as refused:
        send(client, "POST", "/runs/r/decisions", {"period": 1, "decisions": []})

    assert str(refused.value) == (
        "POST /runs/r/decisions: 409 run: the run is finished"
    )


def test_an_unknown_manifest_name_is_refused():
    client = client_of(httpx.Response(200, json={"manifests": []}), [])

    with pytest.raises(
        ValueError, match=r"^name: no stored manifest is named nowhere$"
    ):
        find_manifest(client, "nowhere")


def test_a_server_error_with_a_text_body_raises_with_its_text():
    with pytest.raises(RuntimeError) as refused:
        answer_of(httpx.Response(500, text="Internal Server Error"), "GET", "/x")

    assert str(refused.value) == "GET /x: 500 Internal Server Error"


def test_an_answer_that_is_a_json_list_is_not_a_json_object():
    with pytest.raises(RuntimeError) as refused:
        answer_of(httpx.Response(200, text="[1, 2]"), "GET", "/x")

    assert str(refused.value) == "GET /x: 200 not a JSON object"


def test_an_answer_that_is_not_json_is_not_a_json_object():
    with pytest.raises(RuntimeError) as refused:
        answer_of(httpx.Response(200, text="not json"), "GET", "/x")

    assert str(refused.value) == "GET /x: 200 not a JSON object"


def test_the_shown_description_is_the_description_of_a_twin_run_with_nothing_hidden():
    requests: list[tuple[str, str, dict[str, Any]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/scenarios"):
            return httpx.Response(201, json={"id": "s2", "content": body})
        return httpx.Response(201, json={"id": "r1", "description": {"twin": True}})

    client = httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://server/api/v1"
    )
    content = {"name": "x", "horizon": 3, "hidden": ["lines.items.yield"]}

    description = create_shown_description(client, "m1", 7, content)

    assert requests == [
        (
            "POST",
            "/api/v1/manifests/m1/scenarios",
            {"name": "x-shown", "horizon": 3, "hidden": []},
        ),
        ("POST", "/api/v1/runs", {"scenario_id": "s2", "seed": 7}),
    ]
    assert description == {"twin": True}
