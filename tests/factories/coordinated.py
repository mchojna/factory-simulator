import json
from pathlib import Path
from typing import Any

import httpx2 as httpx

from examples.coordinated_planning import MODEL
from examples.coordinated_planning.transport import FixedOpenAIProvider


# A complete OpenAI reply of the fixed model with a text, its stop reason, its refusal
# and, unless left out, the usage of 20 input and 5 output tokens.
def openai_reply(
    text: str = "[]",
    *,
    usage: bool = True,
    finish_reason: str = "stop",
    refusal: str | None = None,
) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "model": MODEL,
        "service_tier": "default",
        "choices": [
            {
                "message": {"content": text, "refusal": refusal},
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage:
        reply["usage"] = {
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 1},
        }
    return reply


# The fixed OpenAI provider that answers each request with the next of the answers, a
# text or a value written as JSON, keeping the request bodies in sent when given.
def replying_provider(
    answers: list[object], sent: list[dict[str, Any]] | None = None
) -> FixedOpenAIProvider:
    pending = iter(answers)

    def answer(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        value = next(pending)
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return httpx.Response(200, json=openai_reply(text))

    return FixedOpenAIProvider(
        MODEL,
        timeout_seconds=120,
        api_key="fixture-credential",  # pragma: allowlist secret
        transport=httpx.MockTransport(answer),
    )


# The events of the call record of a folder, in order.
def events_of(folder: Path) -> list[dict[str, Any]]:
    rows = (folder / "model-calls.jsonl").read_text().splitlines()
    return [json.loads(row) for row in rows]
