import json
from pathlib import Path
from typing import cast

import httpx2 as httpx
import pytest
from factories.client import app_of
from fastapi.testclient import TestClient

from demos.utils.model import compare_runs, run_model
from demos.utils.providers import AnthropicProvider


@pytest.mark.parametrize("strategy", ["single_prompt", "tools_memory", "coordinated"])
def test_live_demo_dispatches_provider_requests_and_records_actual_responses(
    tmp_path: Path, strategy: str
):
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert request.url == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "test-credential"
        assert body["model"] == "test-hosted-model"
        assert "observation" in body["messages"][0]["content"]
        text = '{"kind":"final","decisions":[]}' if strategy == "tools_memory" else "[]"
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "model": "test-hosted-model",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
        )

    adapter = AnthropicProvider(
        "test-hosted-model",
        timeout_seconds=5,
        api_key="test-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(respond),
    )
    with TestClient(
        app_of(f"duckdb:///{tmp_path / 'runs.duckdb'}", load_examples=False),
        base_url="http://testserver/api/v1",
    ) as test_client:
        summary_path = run_model(
            cast(httpx.Client, test_client),
            "live-demo",
            strategy,
            "anthropic",
            "test-hosted-model",
            7,
            tmp_path / "output",
            adapter=adapter,
        )

    summary = json.loads(summary_path.read_text())
    assert (
        summary["provider_calls"]
        == len(requests)
        == (9 if strategy == "coordinated" else 3)
    )
    assert set(summary["methods"]) == {strategy, "myopic", "no_decisions"}
    assert summary["monetary_spend"] is None
    entries = [
        json.loads(row)
        for row in (summary_path.parent / "model-calls.jsonl").read_text().splitlines()
    ]
    replies = [row for row in entries if row["kind"] == "provider-response"]
    assert all(row["reply"]["http_status"] == 200 for row in replies)
    assert all(row["reply"]["response_body_sha256"] for row in replies)
    assert len([row for row in entries if row["kind"] == "closed-period"]) == 3
    report = json.loads(compare_runs(summary_path, tmp_path / "comparison").read_text())
    assert report["provider_requests_made"] == 0
    assert report["methods"] == summary["methods"]


def test_live_demo_fails_before_creating_a_run_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("missing credentials must fail before simulator requests")

    with (
        httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client,
        pytest.raises(ValueError, match="ANTHROPIC_API_KEY"),
    ):
        run_model(
            client,
            "demo",
            "single_prompt",
            "anthropic",
            "chosen-model",
            7,
            tmp_path,
        )
