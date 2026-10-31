import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import (
    api_client,
    database_file,
    engine_of,
    get_message_by_message,
    post,
    records,
    run_to_the_end,
    start_run,
    submit,
    threaded_api_client,
    tiny_manifest,
)
from sqlalchemy import Engine, event
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool
from starlette.types import Message

from factory_simulator.api.record.models.manifest import Manifest
from factory_simulator.api.record.models.operation import Operation, OperationBody
from factory_simulator.api.record.repositories.operations import create_operation


@pytest.mark.slow
def test_an_unknown_run_keeps_raw_request_and_response_bytes_without_a_run_link():
    body = b'  {"period": 1, "decisions": []} \n'
    with api_client() as client:
        client.client.headers.update(
            {"x-correlation-id": "study-cell", "authorization": "hidden"}
        )
        response = client.post(
            "/api/v1/runs/unknown/decisions",
            content=body,
        )
        [operation] = records(client, Operation, kind="http")
        chunks = records(client, OperationBody, operation_id=operation["position"])

    assert response.status_code == operation["status_code"] == 404
    assert operation["state"] == "completed"
    assert operation["correlation_id"] == "study-cell"
    assert operation["method"] == "POST"
    assert operation["path"] == "/api/v1/runs/unknown/decisions"
    assert operation["run_id"] is None
    assert operation["requested_run_id"] == "unknown"
    assert (
        b"".join(row["body"] for row in chunks if row["direction"] == "request") == body
    )
    assert (
        b"".join(row["body"] for row in chunks if row["direction"] == "response")
        == response.content
    )
    assert "hidden" not in str(operation)


@pytest.mark.slow
def test_an_interrupted_send_retains_generated_bytes_and_observed_transport_facts():
    with api_client() as client:

        def disconnect(message: Message) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with pytest.raises(OSError, match="client disconnected"):
            get_message_by_message(client, "/manifests", disconnect)
        [operation] = records(client, Operation, kind="http")
        chunks = records(client, OperationBody, operation_id=operation["position"])

    body = b'{"manifests":[]}'
    assert operation["state"] == "interrupted"
    assert operation["response_generated"] is True
    assert operation["request_complete"] is True
    assert operation["attempted_bytes"] == len(body)
    assert operation["sent_bytes"] == 0
    assert operation["headers_sent"] is True
    assert operation["exception_type"] == "builtins.OSError"
    assert operation["exception_message"] == "client disconnected"
    assert (
        operation["started_at"] <= operation["generated_at"] <= operation["finished_at"]
    )
    assert operation["duration_ns"] >= 0
    assert b"".join(row["body"] for row in chunks) == body


@pytest.mark.slow
def test_server_startup_and_shutdown_keep_their_order_across_a_restart():
    with database_file() as url:
        with api_client(url) as client:
            first = records(client, Operation)
            assert [(row["kind"], row["state"]) for row in first] == [
                ("startup", "completed")
            ]
        with api_client(url) as client:
            lifecycle = records(client, Operation)

    assert [(row["kind"], row["state"]) for row in lifecycle] == [
        ("startup", "completed"),
        ("shutdown", "completed"),
        ("startup", "completed"),
    ]
    assert [row["position"] for row in lifecycle] == [1, 2, 3]
    assert all(row["method"] is None and row["run_id"] is None for row in lifecycle)


@pytest.mark.slow
def test_a_failed_start_after_database_open_keeps_its_exception():
    def fail_examples(*arguments: object) -> None:
        if str(arguments[2]).startswith("INSERT INTO manifests"):
            raise RuntimeError("startup fixture failure")

    with database_file() as url:
        event.listen(Engine, "before_cursor_execute", fail_examples)
        try:
            with (
                pytest.raises(RuntimeError, match="startup fixture failure"),
                api_client(url, load_examples=True),
            ):
                pass
        finally:
            event.remove(Engine, "before_cursor_execute", fail_examples)
        with api_client(url) as client:
            [failed] = records(client, Operation, state="failed")

    assert failed["kind"] == "startup"
    assert failed["exception_type"] == "builtins.RuntimeError"
    assert failed["exception_message"] == "startup fixture failure"
    assert "startup fixture failure" in failed["exception_traceback"]
    assert failed["started_at"] <= failed["finished_at"]


@pytest.mark.slow
def test_restart_labels_an_abandoned_intent_without_inventing_a_completion_time():
    with database_file() as url:
        with api_client(url) as client:
            abandoned = create_operation(
                engine_of(client), "POST", "/api/v1/runs", "interrupted-cell"
            )
            [pending] = records(client, Operation, position=abandoned.position)
            assert pending["state"] == "received"
            assert pending["finished_at"] is None
        with api_client(url) as client:
            [recovered] = records(client, Operation, position=abandoned.position)

    assert recovered["state"] == "interrupted"
    assert recovered["recovered_at"] is not None
    assert recovered["finished_at"] is None
    assert recovered["duration_ns"] is None
    assert recovered["request_complete"] is False
    assert recovered["response_generated"] is False


@pytest.mark.slow
def test_created_resources_and_run_operations_keep_route_and_resource_links():
    with api_client() as client:
        run = start_run(client)
        run_id = run["id"]
        assert (
            post(client, f"/runs/{run_id}/checks", {"period": 1, "decisions": []})[0]
            == 200
        )
        assert submit(client, run_id, 2, [])[0] == 409
        assert submit(client, run_id, 1, [])[0] == 200
        operations = records(client, Operation, kind="http")

    assert len(operations) == 6
    assert len({row["request_id"] for row in operations}) == 6
    assert [row["status_code"] for row in operations] == [201, 201, 201, 200, 409, 200]
    created_manifest, created_scenario, created_run = operations[:3]
    assert created_run["run_id"] == run_id
    assert created_run["scenario_id"] == run["scenario_id"]
    assert created_run["route"] == "/api/v1/runs"
    assert created_scenario["scenario_id"] == run["scenario_id"]
    assert created_scenario["manifest_id"] == created_manifest["manifest_id"]
    assert created_manifest["manifest_id"] is not None
    assert [row["run_id"] for row in operations[3:]] == [run_id] * 3
    assert operations[-1]["route"] == "/api/v1/runs/{run_id}/decisions"


@pytest.mark.slow
def test_a_fork_operation_links_both_the_parent_and_the_created_run():
    with api_client() as client:
        parent = start_run(client)
        run_to_the_end(client, parent)
        path = f"/runs/{parent['id']}/forks"
        status, fork = post(client, path, {"period": 1})
        [operation] = records(client, Operation, path="/api/v1" + path)

    assert status == 201
    assert operation["run_id"] == parent["id"]
    assert operation["created_run_id"] == fork["id"]
    assert operation["scenario_id"] == parent["scenario_id"]


@pytest.mark.slow
def test_request_targets_and_protocol_headers_survive_without_credential_headers():
    with api_client() as client:
        client.client.headers.update(
            {
                "authorization": "hidden",
                "cookie": "hidden",
                "x-api-key": "hidden",
                "user-agent": "fixture-agent",
                "x-correlation-id": "fixture-cell",
            }
        )
        response = client.get("/api/v1/manifests?label=%20raw&label=two")
        [operation] = records(client, Operation, kind="http")

    assert operation["raw_path"] == b"/api/v1/manifests"
    assert operation["query"] == b"label=%20raw&label=two"
    headers = dict(operation["request_headers"])
    assert headers["user-agent"] == "fixture-agent"
    assert headers["x-correlation-id"] == "fixture-cell"
    assert "hidden" not in str(operation)
    assert (
        dict(operation["response_headers"])["content-type"]
        == response.headers["content-type"]
    )


@pytest.mark.slow
def test_an_unhandled_server_error_keeps_the_fixed_500_body_and_exception():
    with api_client() as client:
        database = engine_of(client)

        def fail_listing(*arguments: object) -> None:
            if str(arguments[2]).startswith("SELECT manifests."):
                raise RuntimeError("controlled server failure")

        event.listen(database, "before_cursor_execute", fail_listing)
        try:
            with pytest.raises(RuntimeError, match="controlled server failure"):
                client.get("/api/v1/manifests")
        finally:
            event.remove(database, "before_cursor_execute", fail_listing)
        [operation] = records(client, Operation, kind="http")
        chunks = records(client, OperationBody, operation_id=operation["position"])

    assert operation["status_code"] == 500
    assert operation["state"] == "failed"
    assert operation["response_generated"] is True
    assert operation["exception_type"] == "builtins.RuntimeError"
    assert operation["exception_message"] == "controlled server failure"
    assert (
        b"".join(row["body"] for row in chunks)
        == b'{"detail":"server: internal error"}'
    )


@pytest.mark.slow
@pytest.mark.parametrize("body", [b"", b"{", b"\xff", b' \n{"period": 1.0000}  '])
def test_a_validation_failure_keeps_every_received_byte(body: bytes):
    with api_client() as client:
        run = start_run(client)
        response = client.post(f"/api/v1/runs/{run['id']}/decisions", content=body)
        [operation] = records(
            client, Operation, path=f"/api/v1/runs/{run['id']}/decisions"
        )
        chunks = records(client, OperationBody, operation_id=operation["position"])

    assert response.status_code == operation["status_code"] == 422
    assert operation["state"] == "completed"
    assert operation["request_complete"] is True
    assert (
        b"".join(row["body"] for row in chunks if row["direction"] == "request") == body
    )


@pytest.mark.slow
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "path", ["/api/v1/openapi.json", "/api/v1/docs", "/docs/oauth2-redirect"]
)
def test_framework_routes_keep_operational_bodies_and_statuses(method: str, path: str):
    with api_client() as client:
        response = client.request(method, path)
        [operation] = records(client, Operation, kind="http")

    assert operation["status_code"] == response.status_code == 200
    assert operation["path"] == path
    assert operation["route"] == path
    assert operation["state"] == "completed"
    assert operation["request_complete"] is True
    assert operation["response_generated"] is True


@pytest.mark.slow
def test_concurrent_requests_keep_distinct_durable_operation_identities():
    with threaded_api_client() as client:
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(
                executor.map(
                    client.get, [f"/api/v1/unknown/{number}" for number in range(8)]
                )
            )
        operations = records(client, Operation, kind="http")

    assert [response.status_code for response in responses] == [404] * 8
    assert len(operations) == len({row["position"] for row in operations}) == 8
    assert len({row["request_id"] for row in operations}) == 8
    assert all(row["state"] == "completed" for row in operations)


@pytest.mark.slow
def test_capture_releases_every_database_connection_before_sending():
    with api_client() as client:
        connection_pool = engine_of(client).pool
        assert isinstance(connection_pool, QueuePool)
        connections: list[int] = []

        def observe(_message: Message) -> None:
            connections.append(connection_pool.checkedout())

        get_message_by_message(client, "/manifests", observe)

    assert connections
    assert all(count == 0 for count in connections)


@pytest.mark.slow
def test_a_large_request_uses_bounded_lossless_body_chunks():
    body = b" \xff" * 40000
    with api_client() as client:
        response = client.post("/api/v1/runs/unknown/decisions", content=body)
        [operation] = records(client, Operation, kind="http")
        chunks = records(
            client,
            OperationBody,
            operation_id=operation["position"],
            direction="request",
        )

    assert response.status_code == 404
    assert [len(row["body"]) for row in chunks] == [65536, 14464]
    assert operation["request_bytes"] == len(body)
    assert b"".join(row["body"] for row in chunks) == body


@pytest.mark.slow
def test_an_unavailable_operational_writer_refuses_before_it_stores_anything():
    with api_client() as client:
        database = engine_of(client)

        def refuse_intent(*arguments: object) -> None:
            if str(arguments[2]).startswith("INSERT INTO operation_identities"):
                raise PoolTimeoutError("controlled unavailable writer")

        event.listen(database, "before_cursor_execute", refuse_intent)
        try:
            response = client.post("/api/v1/manifests", json=tiny_manifest())
        finally:
            event.remove(database, "before_cursor_execute", refuse_intent)
        assert records(client, Operation, kind="http") == []
        assert records(client, Manifest) == []

    assert response.status_code == 503
    assert response.json() == {"detail": "database: no connection was free within 30 s"}


@pytest.mark.slow
def test_a_waiting_operational_write_does_not_block_another_request():
    paused, release = threading.Event(), threading.Event()
    lock = threading.Lock()

    def pause_one_intent(*arguments: object) -> None:
        if not str(arguments[2]).startswith("INSERT INTO operation_identities"):
            return
        with lock:
            first = not paused.is_set()
            paused.set()
        if first:
            assert release.wait(10)

    with threaded_api_client() as client:
        database = engine_of(client)
        event.listen(database, "before_cursor_execute", pause_one_intent)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(client.get, "/api/v1/missing/first")
                assert paused.wait(5)
                second = executor.submit(client.get, "/api/v1/missing/second")
                try:
                    assert second.result(timeout=3).status_code == 404
                finally:
                    release.set()
                assert first.result(timeout=5).status_code == 404
        finally:
            release.set()
            event.remove(database, "before_cursor_execute", pause_one_intent)
