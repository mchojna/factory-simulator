import json
from pathlib import Path
from typing import cast

import httpx2 as httpx
import pytest
from factories.client import app_of
from fastapi.testclient import TestClient

from examples.utils.model import compare_runs, run_model
from examples.utils.providers import (
    AnthropicProvider,
    GoogleProvider,
    OpenAIProvider,
)

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai": OpenAIProvider,
}


def native_reply(provider: str, request: httpx.Request, text: str) -> httpx.Response:
    if provider == "anthropic":
        assert request.url == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "test-credential"
        return httpx.Response(
            200,
            json={
                "id": "response-id",
                "model": "test-hosted-model",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
        )
    if provider == "google":
        assert request.url == (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "test-hosted-model:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-credential"
        return httpx.Response(
            200,
            json={
                "responseId": "response-id",
                "modelVersion": "test-hosted-model",
                "candidates": [
                    {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5},
            },
        )
    assert request.url == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-credential"
    return httpx.Response(
        200,
        json={
            "id": "response-id",
            "model": "test-hosted-model",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        },
    )


@pytest.mark.slow
@pytest.mark.parametrize("strategy", ["single_prompt", "tools_memory", "coordinated"])
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_live_example_dispatches_provider_requests_and_records_actual_responses(
    tmp_path: Path, strategy: str, provider: str
):
    requests: list[dict[str, object]] = []
    model = "test-hosted-model"

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert "observation" in str(body)
        text = '{"kind":"final","decisions":[]}' if strategy == "tools_memory" else "[]"
        return native_reply(provider, request, text)

    adapter = PROVIDERS[provider](
        model,
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
            "live-example",
            strategy,
            provider,
            model,
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
    replies = [row["reply"] for row in entries if row["kind"] == "provider-response"]
    assert len(replies) == len(requests)
    assert all(reply["http_status"] == 200 for reply in replies)
    assert all(reply["response_body_sha256"] for reply in replies)
    assert all(reply["completion"] == "complete" for reply in replies)
    assert all(
        (reply["input_tokens"], reply["output_tokens"]) == (20, 5) for reply in replies
    )
    assert (
        "test-credential" not in (summary_path.parent / "model-calls.jsonl").read_text()
    )
    assert len([row for row in entries if row["kind"] == "closed-period"]) == 3
    report = json.loads(compare_runs(summary_path, tmp_path / "comparison").read_text())
    assert report["provider_requests_made"] == 0
    assert report["methods"] == summary["methods"]


def test_live_example_fails_before_creating_a_run_without_credentials(
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
            "example",
            "single_prompt",
            "anthropic",
            "chosen-model",
            7,
            tmp_path,
        )
