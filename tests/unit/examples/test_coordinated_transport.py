import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from factories.coordinated import openai_reply

from examples.coordinated_planning import transport
from examples.coordinated_planning.transport import (
    Budget,
    LiveProvider,
    is_retryable,
    retry_delay,
)
from examples.utils.providers import ProviderError

MESSAGES = [{"role": "user", "content": "plan"}]
SETTINGS = {"max_output_tokens": 8192}


# A response body that sleeps, sends a partial body or fails before its bytes, and
# records when it opens and closes.
@dataclass(slots=True, kw_only=True)
class Body(httpx.AsyncByteStream):
    content: bytes = b""
    failure: type[Exception] | None = None
    partial: bool = False
    slow: bool = False
    events: list[str] = field(default_factory=list[str])

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.events.append("open")
        if self.slow:
            await asyncio.sleep(1)
        if self.partial:
            yield b'{"choices":'
        if self.failure:
            raise self.failure("simulated failure")
        yield self.content

    async def aclose(self) -> None:
        self.events.append("closed")


# One answer of the mock provider: a status with its body and headers.
@dataclass(frozen=True, slots=True, kw_only=True)
class Answer:
    body: Body
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict[str, str])


# The answer of a complete reply, or of any JSON value with a status.
def answer_of(value: object = None, status: int = 200) -> Answer:
    content = json.dumps(openai_reply() if value is None else value).encode()
    return Answer(body=Body(content=content), status=status)


# The answer of a read timeout before any byte of the body.
def timed_out() -> Answer:
    return Answer(body=Body(failure=httpx.ReadTimeout))


# A live provider with its budget, the request bodies it sends and its waits.
@dataclass(slots=True, kw_only=True)
class Live:
    budget: Budget
    provider: LiveProvider
    bodies: list[bytes]
    waits: list[float]


# A live provider with a budget of 50 USD whose transport gives the answers in order;
# an exception among them is raised instead.
def live_provider(
    folder: Path, answers: list[Answer | Exception], deadline_seconds: float = 600
) -> Live:
    budget = Budget.create(folder / "budget.json", 50, "1.25", "5")
    pending = iter(answers)
    bodies: list[bytes] = []
    waits: list[float] = []

    def answer(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        step = next(pending)
        if isinstance(step, Exception):
            raise step
        return httpx.Response(step.status, stream=step.body, headers=step.headers)

    async def wait(seconds: float) -> None:
        waits.append(seconds)

    provider = LiveProvider(
        budget,
        folder,
        "fixture-credential",  # pragma: allowlist secret
        transport_factory=lambda: httpx.MockTransport(answer),
        sleeper=wait,
        jitter=lambda: 0,
        deadline_seconds=deadline_seconds,
    )
    return Live(budget=budget, provider=provider, bodies=bodies, waits=waits)


# The events of the transport record of a folder, in order.
def transport_events(folder: Path) -> list[dict[str, Any]]:
    rows = (folder / "transport-events.jsonl").read_text().splitlines()
    return [json.loads(row) for row in rows]


def test_a_timeout_before_any_byte_is_sent_again_after_30_seconds(tmp_path: Path):
    live = live_provider(tmp_path, [timed_out(), answer_of()])

    live.provider.complete(MESSAGES, SETTINGS)

    assert live.bodies[0] == live.bodies[1]
    assert live.waits == [30]
    assert live.budget.state["calls"] == 2
    assert live.budget.state["logical_calls"] == 1
    assert live.budget.state["extra_attempts"] == 1
    assert len(live.budget.state["uncertain"]) == 1
    assert Budget(live.budget.path).total() == live.budget.total()


def test_a_timeout_after_a_partial_body_is_not_sent_again(tmp_path: Path):
    partial = Answer(body=Body(failure=httpx.ReadTimeout, partial=True))
    live = live_provider(tmp_path, [partial, answer_of()])

    with pytest.raises(ProviderError):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    last = transport_events(tmp_path)[-1]
    assert last["body_bytes_received"] > 0
    assert not last["retry_eligible"]


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_an_error_status_whose_body_times_out_is_not_sent_again(
    tmp_path: Path, status: int
):
    failing = Answer(body=Body(failure=httpx.ReadTimeout), status=status)
    live = live_provider(tmp_path, [failing, answer_of()])

    with pytest.raises(ProviderError):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    assert live.budget.state["blocked"]


@pytest.mark.parametrize(
    ("status", "code", "kind", "retried"),
    [
        (408, "request_timeout", "", True),
        (500, "", "server_error", True),
        (502, "bad_gateway", "", True),
        (503, "server_is_overloaded", "service_unavailable_error", True),
        (504, "gateway_timeout", "", True),
        (429, "rate_limit_exceeded", "rate_limit_error", True),
        (429, "slow_down", "rate_limit_error", True),
        (429, "insufficient_quota", "rate_limit_error", False),
        (429, "hard_spend_limit", "rate_limit_error", False),
        (429, "billing_hard_limit_reached", "rate_limit_error", False),
        (429, "unknown", "rate_limit_error", False),
        (401, "request_timeout", "", False),
        (403, "server_error", "", False),
        (400, "server_error", "", False),
        (404, "server_error", "", False),
        (503, "authentication_error", "server_error", False),
        (503, "permission_denied", "server_error", False),
        (500, "unknown", "unknown", False),
        (200, "server_error", "", False),
        (501, "server_error", "", False),
    ],
)
def test_only_a_temporary_error_without_quota_or_permission_is_sent_again(
    tmp_path: Path, status: int, code: str, kind: str, retried: bool
):
    error = answer_of({"error": {"code": code, "type": kind}}, status)
    live = live_provider(tmp_path, [error, answer_of()])

    if retried:
        live.provider.complete(MESSAGES, SETTINGS)
        assert len(live.bodies) == 2
        assert len(live.budget.state["uncertain"]) == 1
    else:
        with pytest.raises((ProviderError, RuntimeError)):
            live.provider.complete(MESSAGES, SETTINGS)
        assert len(live.bodies) == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"error": {"type": "server_error"}, "choices": []},
        {"error": {"type": "server_error"}, "output": []},
        {"error": {"type": "server_error"}, "usage": {}},
        {"error": "server_error"},
        [],
        None,
    ],
)
def test_an_error_beside_output_or_without_an_object_is_not_retryable(raw: object):
    assert not is_retryable(503, raw, 100)


@pytest.mark.parametrize(
    "answer",
    [
        Answer(body=Body(content=b"<html>Bad gateway</html>"), status=503),
        Answer(body=Body(content=b"not json")),
        answer_of(openai_reply(usage=False)),
        answer_of(openai_reply(finish_reason="length")),
        answer_of(openai_reply(refusal="no")),
        httpx.ConnectError("offline"),
    ],
    ids=["html", "invalid-json", "missing-usage", "length", "refusal", "transport"],
)
def test_a_received_or_unclassified_failure_blocks_the_budget(
    tmp_path: Path, answer: Answer | Exception
):
    live = live_provider(tmp_path, [answer, answer_of()])

    with pytest.raises((ProviderError, RuntimeError)):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    assert live.budget.state["blocked"]


@pytest.mark.parametrize(
    ("retry_after", "seconds"), [(None, 30), ("45", 45), ("60", 60)]
)
def test_the_wait_is_30_seconds_or_the_retry_after_up_to_60(
    retry_after: str | None, seconds: float
):
    assert retry_delay(retry_after) == seconds


@pytest.mark.parametrize("retry_after", ["invalid", "-1", "NaN"])
def test_an_invalid_retry_after_is_refused(retry_after: str):
    with pytest.raises(RuntimeError, match="Retry-After"):
        retry_delay(retry_after)


def test_a_retry_after_date_gives_its_seconds_and_61_seconds_are_refused():
    assert retry_delay("Thu, 01 Jan 1970 00:00:45 GMT", now=0) == 45
    with pytest.raises(RuntimeError, match="Retry-After"):
        retry_delay("61")


def test_a_retry_after_of_61_seconds_stops_before_a_second_attempt(tmp_path: Path):
    error = Answer(
        body=Body(content=json.dumps({"error": {"type": "server_error"}}).encode()),
        status=503,
        headers={"Retry-After": "61"},
    )
    live = live_provider(tmp_path, [error, answer_of()])

    with pytest.raises(RuntimeError, match="Retry-After"):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    assert live.waits == []


def test_the_deadline_during_the_wait_keeps_the_reservation_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def wait_briefly(*_arguments: object) -> float:
        return 0.001

    monkeypatch.setattr(transport, "retry_delay", wait_briefly)
    live = live_provider(tmp_path, [timed_out(), answer_of()], deadline_seconds=0.02)

    async def wait_too_long(seconds: float) -> None:
        await asyncio.sleep(seconds + 1)

    live.provider.sleeper = wait_too_long

    with pytest.raises(RuntimeError, match="deadline"):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    assert live.budget.state["active"] is None
    assert len(live.budget.state["uncertain"]) == 1
    assert live.budget.state["blocked"]
    kinds = [event["kind"] for event in transport_events(tmp_path)]
    assert "retry-wait-deadline" in kinds


def test_the_deadline_closes_a_slow_body_without_a_second_attempt(tmp_path: Path):
    slow = Answer(body=Body(slow=True))
    live = live_provider(tmp_path, [slow, answer_of()], deadline_seconds=0.02)

    with pytest.raises(ProviderError):
        live.provider.complete(MESSAGES, SETTINGS)

    assert slow.body.events == ["open", "closed"]
    assert len(live.bodies) == 1
    assert live.budget.state["blocked"]


def test_a_wait_longer_than_the_deadline_is_not_started(tmp_path: Path):
    live = live_provider(tmp_path, [timed_out(), answer_of()], deadline_seconds=10)

    with pytest.raises(RuntimeError, match="deadline"):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == 1
    assert live.waits == []


def test_each_attempt_closes_its_body_before_the_next_one(tmp_path: Path):
    events: list[str] = []
    first = Answer(body=Body(failure=httpx.ReadTimeout, events=events))
    second = Answer(
        body=Body(content=json.dumps(openai_reply()).encode(), events=events)
    )
    live = live_provider(tmp_path, [first, second])

    live.provider.complete(MESSAGES, SETTINGS)

    assert events == ["open", "closed", "open", "closed"]


@pytest.mark.parametrize(
    ("counter", "used", "attempts"),
    [("extra_attempts", 20, 1), ("calls", 815, 0), ("logical_calls", 795, 0)],
)
def test_a_budget_out_of_attempts_or_calls_stops_the_request(
    tmp_path: Path, counter: str, used: int, attempts: int
):
    live = live_provider(tmp_path, [timed_out(), answer_of()])
    live.budget.state[counter] = used
    live.budget.save()

    with pytest.raises(RuntimeError, match="exhausted"):
        live.provider.complete(MESSAGES, SETTINGS)

    assert len(live.bodies) == attempts


def test_a_reservation_that_cannot_be_saved_sends_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    live = live_provider(tmp_path, [answer_of()])
    live.budget.begin()

    def fail() -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(live.budget, "save", fail)

    with pytest.raises(OSError, match="disk"):
        live.budget.reserve(live.provider.request_payload(MESSAGES, SETTINGS), 1, 1)

    assert live.bodies == []


def test_a_cap_below_the_reservation_sends_no_request(tmp_path: Path):
    live = live_provider(tmp_path, [answer_of()])
    live.budget.state["cap"] = "0.001"
    live.budget.save()

    with pytest.raises(RuntimeError, match="exhausted"):
        live.provider.complete(MESSAGES, SETTINGS)

    assert live.bodies == []


@pytest.mark.parametrize(
    ("cap", "rate"),
    [("0", "1"), ("51", "1"), ("NaN", "1"), ("1", "0"), ("1", "Infinity")],
)
def test_a_cap_above_50_or_a_value_not_positive_and_finite_is_refused(
    tmp_path: Path, cap: str, rate: str
):
    with pytest.raises(ValueError, match="budget"):
        Budget.create(tmp_path / "budget.json", cap, rate, 5)

    assert not (tmp_path / "budget.json").exists()


def test_a_new_budget_never_replaces_an_existing_one(tmp_path: Path):
    path = tmp_path / "budget.json"
    Budget.create(path, 50, 1.25, 5)
    before = path.read_bytes()

    with pytest.raises(FileExistsError):
        Budget.create(path, 50, 1.25, 5)

    assert path.read_bytes() == before
