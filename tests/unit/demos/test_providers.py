import base64
import hashlib
import json
from decimal import Decimal
from typing import cast

import httpx2 as httpx
import pytest

from demos.utils.providers import (
    AnthropicProvider,
    GoogleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderError,
)


def test_openai_adapter_records_the_exact_http_body_without_credentials():
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "fixed-model-20261001",
                "system_fingerprint": "revision-9",
                "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 2},
            },
        )

    messages = [{"role": "user", "content": "exact input"}]
    adapter = OpenAIProvider(
        "requested-alias",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )
    reply = adapter.complete(
        messages,
        {"temperature": 0.0, "max_output_tokens": 24},
    )

    request_body = json.loads(sent[0].content)
    assert "fixture-credential" not in str(reply.request)
    assert request_body["messages"] == messages
    assert request_body["max_completion_tokens"] == 24
    assert reply.response["id"] == "response-1"
    assert reply.provider_revision == "revision-9"
    assert reply.input_tokens == 17
    assert reply.output_tokens == 2


def test_provider_reply_keeps_exact_numeric_response_bytes_and_status():
    response_body = (
        b'{"id":"response-raw","model":"fixture-model",'
        b'"choices":[{"message":{"content":"[]"},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":1,"completion_tokens":1},'
        b'"measurement":0.12345678901234567890123456789}'
    )
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=response_body)

    adapter = OpenAIProvider(
        "fixture-model",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )
    reply = adapter.complete(
        [{"role": "user", "content": "exact"}], {"max_output_tokens": 8}
    )

    assert reply.http_status == 200
    assert base64.b64decode(cast(str, reply.request_body_base64)) == sent[0].content
    assert base64.b64decode(cast(str, reply.response_body_base64)) == response_body
    assert reply.request_body_sha256 == hashlib.sha256(sent[0].content).hexdigest()
    assert reply.response_body_sha256 == hashlib.sha256(response_body).hexdigest()
    assert reply.response["measurement"] == Decimal("0.12345678901234567890123456789")


def test_openai_adapter_refuses_unsupported_settings_before_http_dispatch():
    dispatched = False

    def answer(_request: httpx.Request) -> httpx.Response:
        nonlocal dispatched
        dispatched = True
        return httpx.Response(200, json={})

    adapter = OpenAIProvider(
        "requested-alias",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )

    with pytest.raises(ValueError, match="unsupported OpenAI settings"):
        adapter.complete([], {"reasoning_effort": "high"})

    assert not dispatched


def test_openai_adapter_refuses_missing_credentials_before_provider_work(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        OpenAIProvider("requested-alias", timeout_seconds=3.0)


def test_openai_adapter_keeps_the_raw_error_response():
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"type": "rate_limit_exceeded", "message": "slow down"}},
        )

    adapter = OpenAIProvider(
        "requested-alias",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )

    with pytest.raises(ProviderError, match="rate_limit_exceeded") as failure:
        adapter.complete(
            [{"role": "user", "content": "exact input"}],
            {"max_output_tokens": 8},
        )

    assert failure.value.reply is not None
    assert failure.value.reply.response["error"] == {
        "type": "rate_limit_exceeded",
        "message": "slow down",
    }
    assert failure.value.reply.http_status == 429
    assert base64.b64decode(cast(str, failure.value.reply.response_body_base64))
    assert (
        failure.value.reply.response_body_sha256
        == hashlib.sha256(
            base64.b64decode(cast(str, failure.value.reply.response_body_base64))
        ).hexdigest()
    )
    assert "fixture-credential" not in str(failure.value.reply.request)


def test_openai_adapter_keeps_non_json_http_error_bytes():
    raw = b"upstream unavailable"
    adapter = OpenAIProvider(
        "requested-alias",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(502, content=raw)
        ),
    )

    with pytest.raises(ProviderError) as failure:
        adapter.complete(
            [{"role": "user", "content": "exact input"}],
            {"max_output_tokens": 8},
        )

    assert failure.value.reply is not None
    assert failure.value.reply.http_status == 502
    assert base64.b64decode(cast(str, failure.value.reply.response_body_base64)) == raw


@pytest.mark.parametrize(
    ("provider_type", "environment_key", "endpoint", "response"),
    [
        (
            AnthropicProvider,
            "ANTHROPIC_API_KEY",
            "https://api.anthropic.com/v1/messages",
            {
                "id": "message-1",
                "type": "message",
                "model": "returned-model",
                "content": [{"type": "text", "text": "[]"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 17, "output_tokens": 2},
            },
        ),
        (
            GoogleProvider,
            "GOOGLE_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/models/requested-model:generateContent",
            {
                "responseId": "response-1",
                "modelVersion": "returned-model-revision",
                "candidates": [
                    {
                        "content": {"parts": [{"text": "[]"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 17,
                    "candidatesTokenCount": 2,
                },
            },
        ),
        (
            OpenRouterProvider,
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "id": "response-1",
                "model": "returned-model",
                "provider": "selected-route",
                "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 2},
            },
        ),
    ],
)
def test_hosted_adapters_keep_the_common_messages_and_capture_raw_replies(
    provider_type: type[AnthropicProvider | GoogleProvider | OpenRouterProvider],
    environment_key: str,
    endpoint: str,
    response: dict[str, object],
):
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=response)

    adapter = provider_type(
        "requested-model",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )
    messages = [
        {"role": "system", "content": "Choose factory decisions."},
        {"role": "user", "content": '{"manifest":{},"period":1}'},
    ]
    reply = adapter.complete(messages, {"temperature": 0.25, "max_output_tokens": 24})

    request_body = json.loads(sent[0].content)
    assert str(sent[0].url) == endpoint
    assert response == reply.response
    assert reply.requested_model == "requested-model"
    assert reply.returned_model == (
        "returned-model-revision"
        if environment_key == "GOOGLE_API_KEY"
        else "returned-model"
    )
    assert reply.text == "[]"
    assert reply.response_id in {"message-1", "response-1"}
    assert reply.stop_reason in {"end_turn", "STOP", "stop"}
    assert reply.input_tokens == 17
    assert reply.output_tokens == 2
    if environment_key != "GOOGLE_API_KEY":
        assert request_body["model"] == "requested-model"
    if environment_key == "ANTHROPIC_API_KEY":
        assert sent[0].headers["x-api-key"] == "fixture-credential"
    elif environment_key == "GOOGLE_API_KEY":
        assert sent[0].headers["x-goog-api-key"] == "fixture-credential"
    else:
        assert sent[0].headers["authorization"] == "Bearer fixture-credential"
        assert sent[0].headers["x-openrouter-metadata"] == "enabled"
    assert adapter.count_input_tokens(messages) > 0
    if environment_key == "ANTHROPIC_API_KEY":
        assert request_body["system"] == messages[0]["content"]
        assert request_body["messages"] == messages[1:]
        assert request_body["max_tokens"] == 24
    elif environment_key == "GOOGLE_API_KEY":
        assert (
            request_body["systemInstruction"]["parts"][0]["text"]
            == messages[0]["content"]
        )
        assert request_body["contents"][0]["parts"][0]["text"] == messages[1]["content"]
        assert request_body["generationConfig"]["maxOutputTokens"] == 24
        assert "model" not in request_body
    else:
        assert request_body["messages"] == messages
        assert request_body["max_tokens"] == 24
        assert reply.routing_identity == "selected-route"


@pytest.mark.parametrize(
    "provider_type",
    [
        AnthropicProvider,
        GoogleProvider,
        OpenRouterProvider,
    ],
)
def test_hosted_adapters_refuse_unsupported_settings_before_dispatch(
    provider_type: type[AnthropicProvider | GoogleProvider | OpenRouterProvider],
):
    dispatched = False

    def answer(_request: httpx.Request) -> httpx.Response:
        nonlocal dispatched
        dispatched = True
        return httpx.Response(200, json={})

    adapter = provider_type(
        "requested-model",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )

    with pytest.raises(ValueError, match=r"unsupported .* settings"):
        adapter.complete([], {"reasoning_effort": "high", "max_output_tokens": 8})

    assert not dispatched


@pytest.mark.parametrize(
    ("provider_type", "environment_key"),
    [
        (AnthropicProvider, "ANTHROPIC_API_KEY"),
        (GoogleProvider, "GOOGLE_API_KEY"),
        (OpenRouterProvider, "OPENROUTER_API_KEY"),
    ],
)
def test_hosted_adapters_refuse_missing_credentials(
    provider_type: type[AnthropicProvider | GoogleProvider | OpenRouterProvider],
    environment_key: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv(environment_key, raising=False)

    with pytest.raises(ValueError, match=f"{environment_key} is required"):
        provider_type("requested-model", timeout_seconds=3.0)


@pytest.mark.parametrize(
    ("provider_type", "environment_key", "response"),
    [
        (
            AnthropicProvider,
            "ANTHROPIC_API_KEY",
            {"type": "error", "error": {"type": "rate_limit_error"}},
        ),
        (
            GoogleProvider,
            "GOOGLE_API_KEY",
            {"error": {"status": "RESOURCE_EXHAUSTED", "message": "slow down"}},
        ),
        (
            OpenRouterProvider,
            "OPENROUTER_API_KEY",
            {"error": {"type": "rate_limit_exceeded", "message": "slow down"}},
        ),
    ],
)
def test_hosted_adapters_retain_rate_limit_response_bodies(
    provider_type: type[AnthropicProvider | GoogleProvider | OpenRouterProvider],
    environment_key: str,
    response: dict[str, object],
):
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=response)

    adapter = provider_type(
        "requested-model",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )

    with pytest.raises(ProviderError, match="rate_limit") as failure:
        adapter.complete([], {"max_output_tokens": 8})

    assert failure.value.reply is not None
    assert failure.value.reply.response == response
    assert environment_key not in str(failure.value.reply.request)


@pytest.mark.parametrize(
    ("provider_type", "response"),
    [
        (AnthropicProvider, {"content": [{"type": "text", "text": "[]"}]}),
        (GoogleProvider, {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}),
        (
            OpenRouterProvider,
            {"choices": [{"message": {"content": "[]"}}]},
        ),
    ],
)
def test_hosted_adapters_leave_unreported_usage_unknown(
    provider_type: type[AnthropicProvider | GoogleProvider | OpenRouterProvider],
    response: dict[str, object],
):
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    adapter = provider_type(
        "requested-model",
        timeout_seconds=3.0,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )

    reply = adapter.complete([], {"max_output_tokens": 8})

    assert reply.input_tokens is None
    assert reply.output_tokens is None
