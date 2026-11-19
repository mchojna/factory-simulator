"""The provider requests of the example: the fixed model, the budget and the retries.

Examples:
    >>> TRANSPORT_POLICY["max_attempts_per_call"]
    2
"""

import asyncio
import base64
import copy
import datetime
import email.utils
import hashlib
import json
import math
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Self, cast

import httpx2 as httpx

from examples.coordinated_planning import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
)
from examples.coordinated_planning.files import append_json_line, write_json
from examples.utils.providers import (
    HttpEvidence,
    OpenAIProvider,
    ProviderError,
    ProviderReply,
    http_evidence,
)
from factory_simulator.benchmark.client import JsonObject

# The timeouts in seconds, the attempt limits and the retry waits of every request.
TRANSPORT_POLICY: JsonObject = {
    "read_timeout": 240,
    "connect_timeout": 10,
    "write_timeout": 20,
    "pool_timeout": 5,
    "logical_deadline": 600,
    "max_attempts_per_call": 2,
    "max_extra_attempts": 20,
    "max_new_logical_calls": 795,
    "max_new_http_attempts": 815,
    "retry_wait_base": 30,
    "retry_wait_jitter": 5,
    "max_retry_after": 60,
}
# The largest spending cap of one command, in USD.
MAX_CAP_USD = 50
# The most input tokens of a request. The bytes of its messages and a margin bound the
# tokens of a request before it is sent.
_MAX_INPUT_TOKENS = 272000
_MARGIN_BYTES = 1024
# The schema of the budget file.
_BUDGET_SCHEMA = "coordinated-planning-budget-1"
# A function that gives the HTTP transport of one attempt.
type TransportFactory = Callable[[], httpx.AsyncBaseTransport]
# The response headers kept in the transport events.
_KEPT_HEADERS = ("x-request-id", "request-id", "retry-after", "content-type")
# The words of an error code or type that rule out a retry.
_FINAL_ERROR_WORDS = (
    "quota",
    "billing",
    "spend",
    "credit",
    "auth",
    "permission",
    "budget",
    "payment",
)
# The error codes and types of a temporary provider failure.
_TEMPORARY_ERRORS = frozenset(
    {
        "server_error",
        "internal_server_error",
        "service_unavailable_error",
        "server_is_overloaded",
        "request_timeout",
        "timeout",
        "gateway_timeout",
        "bad_gateway",
        "overloaded_error",
    }
)
# The fields of a response that hold output; an error beside one is not retried.
_OUTPUT_FIELDS = ("choices", "output", "usage", "completion", "model", "id")


class FixedOpenAIProvider(OpenAIProvider):
    """The OpenAI adapter with the model, reasoning effort and service tier fixed.

    Attributes:
        model (str): The requested model identifier.

    Examples:
        >>> provider = FixedOpenAIProvider(
        ...     MODEL,
        ...     timeout_seconds=1,
        ...     api_key="example",  # pragma: allowlist secret
        ... )
        >>> provider.request_payload([], {"max_output_tokens": 8192})["service_tier"]
        'default'
    """

    def request_payload(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> dict[str, object]:
        """Build the request body of the fixed model and generation settings.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            dict[str, object]: The request body sent to the provider.

        Raises:
            ValueError: If the model or the settings differ from the fixed ones.

        Examples:
            >>> provider = FixedOpenAIProvider(
            ...     "other-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.request_payload([], {"max_output_tokens": 8192})
            Traceback (most recent call last):
            ...
            ValueError: request: model or settings differ from the fixed configuration
        """
        if self.model != MODEL or settings != {"max_output_tokens": MAX_OUTPUT_TOKENS}:
            raise ValueError(
                "request: model or settings differ from the fixed configuration"
            )
        request = super().request_payload(messages, settings)
        request.update(reasoning_effort=REASONING_EFFORT, service_tier=SERVICE_TIER)
        return request


class Budget:
    """The spending budget of one command, kept in a file after every change.

    An attempt reserves the cost of its whole input and of the most output tokens
    before it is sent. A reply settles the reservation at its reported usage. An
    attempt without a reply keeps its reservation as uncertain.

    Attributes:
        path (Path): The budget file.
        state (dict[str, Any]): The cap, the rates, the spending and the attempts.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
        ...     budget.total()
        Decimal('0')
    """

    def __init__(self, path: Path) -> None:
        """Read a budget file and check its policy, model, cap and rates.

        Args:
            path (Path): The budget file.

        Raises:
            RuntimeError: If the schema, the policy or the model differ from these.
            ValueError: If the cap or a rate is not positive and finite, or the cap is
                above 50 USD.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     path = Path(folder) / "budget.json"
            ...     _ = Budget.create(path, 1, 1, 5)
            ...     Budget(path).state["cap"]
            '1'
        """
        self.path = path
        self.state: JsonObject = json.loads(path.read_text())
        if (
            self.state.get("schema") != _BUDGET_SCHEMA
            or self.state.get("policy") != TRANSPORT_POLICY
        ):
            raise RuntimeError(f"{path}: schema or policy differs from this transport")
        if self.state.get("model") != MODEL:
            raise RuntimeError(f"{path}: model differs from {MODEL}")
        for key in ("cap", "input_rate", "output_rate"):
            value = Decimal(self.state[key])
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{path}: {key} is not positive and finite")
        if Decimal(self.state["cap"]) > MAX_CAP_USD:
            raise ValueError(f"{path}: cap is above {MAX_CAP_USD} USD")
        self.total()

    @classmethod
    def create(
        cls, path: Path, cap: object, input_rate: object, output_rate: object
    ) -> Self:
        """Write a new budget file with nothing spent.

        Args:
            path (Path): The new budget file.
            cap (object): The spending cap in USD.
            input_rate (object): The USD per million input tokens.
            output_rate (object): The USD per million output tokens, reasoning
                included.

        Returns:
            Budget: The budget of the new file.

        Raises:
            ValueError: If a value is not positive and finite, or the cap is above
                50 USD.
            FileExistsError: If the file exists.

        Examples:
            >>> Budget.create(Path("budget.json"), 51, 1, 5)
            Traceback (most recent call last):
            ...
            ValueError: budget: cap or rate is not positive and finite, or above 50 USD
        """
        values = [Decimal(str(value)) for value in (cap, input_rate, output_rate)]
        if (
            any(not value.is_finite() or value <= 0 for value in values)
            or values[0] > MAX_CAP_USD
        ):
            raise ValueError(
                "budget: cap or rate is not positive and finite, or above "
                f"{MAX_CAP_USD} USD"
            )
        state: JsonObject = {
            "schema": _BUDGET_SCHEMA,
            "policy": TRANSPORT_POLICY,
            "model": MODEL,
            "cap": str(values[0]),
            "input_rate": str(values[1]),
            "output_rate": str(values[2]),
            "spent": "0",
            "uncertain": [],
            "active": None,
            "calls": 0,
            "logical_calls": 0,
            "extra_attempts": 0,
            "blocked": False,
            "entries": [],
            "cost_method": (
                "All input charged at configured uncached rate; reasoning included in "
                "output. Estimate, not invoice."
            ),
        }
        with path.open("x") as stream:
            json.dump(state, stream, indent=2)
        return cls(path)

    def save(self) -> None:
        """Write the state to the budget file.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.state["calls"] = 3
            ...     budget.save()
            ...     Budget(budget.path).state["calls"]
            3
        """
        write_json(self.path, self.state)

    def total(self) -> Decimal:
        """Give the spending with every uncertain and active reservation.

        Returns:
            Decimal: The USD that the cap no longer leaves free.

        Raises:
            RuntimeError: If an amount is negative or not finite.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.state["uncertain"] = [{"reserved_usd": "0.25"}]
            ...     budget.total()
            Decimal('0.25')
        """
        values = [
            self.state["spent"],
            *[entry["reserved_usd"] for entry in self.state["uncertain"]],
        ]
        if self.state["active"]:
            values.append(self.state["active"]["reserved_usd"])
        amounts = [Decimal(value) for value in values]
        if any(not amount.is_finite() or amount < 0 for amount in amounts):
            raise RuntimeError(f"{self.path}: an amount is negative or not finite")
        return sum(amounts, Decimal(0))

    def begin(self) -> int:
        """Count a new logical call, before its first attempt.

        Returns:
            int: The number of the logical call.

        Raises:
            RuntimeError: If the budget is blocked, an attempt is active or the
                logical calls run out.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.begin()
            1
        """
        if self.state["blocked"] or self.state["active"]:
            raise RuntimeError("budget: is blocked or an attempt is still active")
        if self.state["logical_calls"] >= TRANSPORT_POLICY["max_new_logical_calls"]:
            raise RuntimeError("budget: logical calls are exhausted")
        self.state["logical_calls"] += 1
        self.save()
        return self.state["logical_calls"]

    def reserve(
        self, request: JsonObject, logical_call: int, attempt: int
    ) -> JsonObject:
        """Reserve the most cost of one attempt, before it is sent.

        Args:
            request (dict[str, Any]): The request body.
            logical_call (int): The number of the current logical call.
            attempt (int): The attempt of the logical call, 1 or 2.

        Returns:
            dict[str, Any]: The active reservation: the attempt, its logical call, its
                number among all attempts and its USD.

        Raises:
            RuntimeError: If the budget is blocked, the attempt is not the next one,
                the attempts run out, the request differs from the fixed one, its input
                is above the token limit or the cap leaves too little.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> request = {
            ...     "model": MODEL,
            ...     "messages": [{"role": "user", "content": "plan"}],
            ...     "reasoning_effort": "low",
            ...     "service_tier": "default",
            ...     "max_completion_tokens": 8192,
            ... }
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.reserve(request, budget.begin(), 1)["reserved_usd"]
            '0.041988'
        """
        if self.state["blocked"] or self.state["active"]:
            raise RuntimeError("budget: is blocked or an attempt is still active")
        if attempt not in (1, 2) or logical_call != self.state["logical_calls"]:
            raise RuntimeError("budget: attempt is not the next one of its call")
        if self.state["calls"] >= TRANSPORT_POLICY["max_new_http_attempts"]:
            raise RuntimeError("budget: HTTP attempts are exhausted")
        if (
            attempt == 2
            and self.state["extra_attempts"] >= TRANSPORT_POLICY["max_extra_attempts"]
        ):
            raise RuntimeError("budget: extra attempts are exhausted")
        fixed = {
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "service_tier": SERVICE_TIER,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
        }
        if any(request.get(key) != value for key, value in fixed.items()):
            raise RuntimeError("request: differs from the fixed configuration")
        upper = (
            sum(
                len(message["content"].encode("utf-8"))
                for message in request["messages"]
            )
            + _MARGIN_BYTES
        )
        if upper > _MAX_INPUT_TOKENS:
            raise RuntimeError(f"request: input is above {_MAX_INPUT_TOKENS} tokens")
        reservation = self._cost(upper, MAX_OUTPUT_TOKENS)
        if self.total() + reservation > Decimal(self.state["cap"]):
            raise RuntimeError("budget: is exhausted before the request")
        call = self.state["calls"] + 1
        self.state["active"] = {
            "call": call,
            "logical_call_id": logical_call,
            "attempt": attempt,
            "reserved_usd": str(reservation),
        }
        self.state["calls"] = call
        self.state["extra_attempts"] += int(attempt == 2)
        self.save()
        return copy.deepcopy(self.state["active"])

    def mark_uncertain(self, reason: str) -> None:
        """Keep the active reservation as uncertain, when an attempt has no reply.

        Args:
            reason (str): The failure of the attempt.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.state["active"] = {"reserved_usd": "0.1"}
            ...     budget.mark_uncertain("timeout")
            ...     budget.state["uncertain"]
            [{'reserved_usd': '0.1', 'reason': 'timeout'}]
        """
        if self.state["active"]:
            self.state["uncertain"].append({**self.state["active"], "reason": reason})
            self.state["active"] = None
            self.save()

    def block(self, reason: str) -> None:
        """Block every later attempt, keeping the active reservation as uncertain.

        Args:
            reason (str): The failure that stops the command.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.block("ProviderError")
            ...     budget.begin()
            Traceback (most recent call last):
            ...
            RuntimeError: budget: is blocked or an attempt is still active
        """
        self.mark_uncertain(reason)
        self.state.update(blocked=True, block_reason=reason)
        self.save()

    def settle(self, reply: ProviderReply) -> None:
        """Replace the active reservation with the cost of the reported usage.

        Args:
            reply (ProviderReply): The reply of the active attempt.

        Raises:
            RuntimeError: If no attempt is active, the model, the tier or the usage
                differ from the request, or the spending passes the cap.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.settle(cast(ProviderReply, None))
            Traceback (most recent call last):
            ...
            RuntimeError: budget: no attempt is active
        """
        active = self.state["active"]
        if active is None:
            raise RuntimeError("budget: no attempt is active")
        if (
            reply.returned_model != MODEL
            or reply.response.get("service_tier") != SERVICE_TIER
        ):
            raise RuntimeError("reply: model or service tier differs from the request")
        if any(
            type(tokens) is not int or tokens < 0
            for tokens in (reply.input_tokens, reply.output_tokens)
        ):
            raise RuntimeError("reply: usage is missing or invalid")
        input_tokens = cast(int, reply.input_tokens)
        output_tokens = cast(int, reply.output_tokens)
        if input_tokens > _MAX_INPUT_TOKENS or output_tokens > MAX_OUTPUT_TOKENS:
            raise RuntimeError("reply: usage is above the request limits")
        if reply.reasoning_tokens is not None and (
            type(reply.reasoning_tokens) is not int
            or not 0 <= reply.reasoning_tokens <= output_tokens
        ):
            raise RuntimeError("reply: reasoning usage is invalid")
        cost = self._cost(input_tokens, output_tokens)
        if cost > Decimal(active["reserved_usd"]):
            raise RuntimeError("reply: usage costs more than its reservation")
        usage = cast(dict[str, object], reply.response.get("usage", {}))
        self.state["entries"].append(
            {
                **active,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reply.reasoning_tokens,
                "conservative_cost_usd": str(cost),
                "prompt_tokens_details": usage.get("prompt_tokens_details"),
            }
        )
        self.state["spent"] = str(Decimal(self.state["spent"]) + cost)
        self.state["active"] = None
        self.save()
        if self.total() > Decimal(self.state["cap"]):
            raise RuntimeError("budget: spending is above the cap")

    def _cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Give the USD of a number of input and output tokens at the budget rates.

        Args:
            input_tokens (int): The input tokens.
            output_tokens (int): The output tokens, reasoning included.

        Returns:
            Decimal: The cost in USD.
        """
        return (
            Decimal(input_tokens) * Decimal(self.state["input_rate"])
            + Decimal(output_tokens) * Decimal(self.state["output_rate"])
        ) / 1000000


def is_retryable(
    status: int | None, raw: object, body_bytes: int, error_kind: str | None = None
) -> bool:
    """Tell whether a failed attempt can be sent again.

    A timeout before any byte of the body is retried. A received error is retried only
    when it is a complete JSON error of a temporary failure, with no output beside it
    and no word of quota, billing, credit or permission in its code or type.

    Args:
        status (int | None): The HTTP status, or None before a response.
        raw (object): The decoded body, or None.
        body_bytes (int): The bytes of the body received.
        error_kind (str | None, optional): `timeout`, `logical_deadline` or
            `transport` when the attempt raised; None when not given.

    Returns:
        bool: Whether the attempt can be sent again.

    Examples:
        >>> is_retryable(503, {"error": {"type": "server_error"}}, 40)
        True
        >>> is_retryable(429, {"error": {"code": "insufficient_quota"}}, 40)
        False
    """
    if error_kind:
        return error_kind == "timeout" and body_bytes == 0 and status in (None, 200)
    if not isinstance(raw, dict):
        return False
    response = cast(dict[str, object], raw)
    if not isinstance(response.get("error"), dict) or any(
        key in response for key in _OUTPUT_FIELDS
    ):
        return False
    error = cast(dict[str, object], response["error"])
    code = str(error.get("code", "")).lower()
    kind = str(error.get("type", "")).lower()
    if any(word in code or word in kind for word in _FINAL_ERROR_WORDS):
        return False
    if status == 429:
        return code in {"rate_limit_exceeded", "slow_down"} and kind in {
            "rate_limit_error",
            "",
        }
    return status in {408, 500, 502, 503, 504} and bool(
        {code, kind} & _TEMPORARY_ERRORS
    )


def retry_delay(
    retry_after: str | None, jitter: float = 0, now: float | None = None
) -> float:
    """Give the seconds to wait before an attempt is sent again.

    Args:
        retry_after (str | None): The `Retry-After` header, in seconds or as a date.
        jitter (float, optional): The seconds added to the wait; 0 when not given.
        now (float | None, optional): The current time as a timestamp; the clock when
            not given.

    Returns:
        float: The base wait or the wait the provider asks for, whichever is longer,
            with the jitter.

    Raises:
        RuntimeError: If the header is invalid or asks for more than 60 seconds.

    Examples:
        >>> retry_delay(None)
        30.0
        >>> retry_delay("45", jitter=2)
        47.0
    """
    wait = float(TRANSPORT_POLICY["retry_wait_base"])
    if retry_after is not None:
        try:
            asked = float(retry_after)
        except TypeError, ValueError:
            try:
                date = email.utils.parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=datetime.UTC)
                asked = date.timestamp() - (time.time() if now is None else now)
            except (TypeError, ValueError, OverflowError) as error:
                raise RuntimeError("Retry-After: is invalid") from error
        if not math.isfinite(asked) or asked < 0:
            raise RuntimeError("Retry-After: is invalid")
        if asked > TRANSPORT_POLICY["max_retry_after"]:
            raise RuntimeError("Retry-After: is above the longest wait")
        wait = max(wait, asked)
    return wait + jitter


# The outcome of one HTTP attempt: its status, the bytes received, the decoded body,
# the kept headers and the failure that ended it.
@dataclass(slots=True, kw_only=True)
class _Attempt:
    status: int | None = None
    chunks: list[bytes] = field(default_factory=list[bytes])
    raw: object = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    error_kind: str | None = None
    response: httpx.Response | None = None


class LiveProvider(FixedOpenAIProvider):
    """The fixed OpenAI adapter that charges a budget and retries one failed attempt.

    Each logical call has at most two attempts within a deadline of 600 seconds. A
    partial reply is never sent again. Every attempt is recorded in
    `transport-events.jsonl`, with each request and reply in its own file.

    Attributes:
        model (str): The requested model identifier.
        budget (Budget): The spending budget.
        folder (Path): The directory of the transport record.
        transport_factory (TransportFactory | None): The transport of each attempt;
            None uses the network.
        sleeper (Callable[[float], Awaitable[None]]): The wait between attempts.
        clock (Callable[[], float]): The monotonic clock in seconds.
        deadline_seconds (float): The deadline of one logical call.
        jitter (Callable[[], float]): The seconds added to each wait.
        case (str | None): The case of the current requests.
        context (dict[str, Any]): The case, period, call and role of the current
            request.
        logical_call (int): The number of the current logical call.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
        ...     provider = LiveProvider(
        ...         budget,
        ...         Path(folder),
        ...         "example",  # pragma: allowlist secret
        ...     )
        ...     provider.deadline_seconds
        600
    """

    def __init__(
        self,
        budget: Budget,
        folder: Path,
        api_key: str,
        *,
        transport_factory: TransportFactory | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        deadline_seconds: float = TRANSPORT_POLICY["logical_deadline"],
        jitter: Callable[[], float] | None = None,
    ) -> None:
        """Create the provider with its budget, record folder and credential.

        Args:
            budget (Budget): The spending budget.
            folder (Path): The directory of the transport record.
            api_key (str): The OpenAI credential.
            transport_factory (TransportFactory | None, optional): The transport of
                each attempt; the network when not given.
            sleeper (Callable[[float], Awaitable[None]], optional): The wait between
                attempts; `asyncio.sleep` when not given.
            clock (Callable[[], float], optional): The monotonic clock in seconds;
                `time.monotonic` when not given.
            deadline_seconds (float, optional): The deadline of one logical call; 600
                when not given.
            jitter (Callable[[], float] | None, optional): The seconds added to each
                wait; a uniform draw from 0 through 5 when not given.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     LiveProvider(
            ...         budget,
            ...         Path(folder),
            ...         "example",  # pragma: allowlist secret
            ...     ).model
            'gpt-6.1-terra'
        """
        super().__init__(
            MODEL, timeout_seconds=TRANSPORT_POLICY["read_timeout"], api_key=api_key
        )
        self.budget = budget
        self.folder = folder
        self.transport_factory = transport_factory
        self.sleeper = sleeper
        self.clock = clock
        self.deadline_seconds = deadline_seconds
        self.jitter = jitter or (
            # The jitter spreads retries; it needs no secure randomness.
            lambda: random.uniform(0, TRANSPORT_POLICY["retry_wait_jitter"])  # noqa: S311
        )
        self.case: str | None = None
        self.context: JsonObject = {}
        self.logical_call = 0

    def set_context(self, request: JsonObject) -> None:
        """Keep the case, period, call and role of the request the agent records.

        Args:
            request (dict[str, Any]): The provider-request event of the agent.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     provider = LiveProvider(
            ...         budget,
            ...         Path(folder),
            ...         "example",  # pragma: allowlist secret
            ...     )
            ...     provider.set_context(
            ...         {
            ...             "period": 1,
            ...             "call_id": 3,
            ...             "messages": [
            ...                 {"role": "user", "content": '{"role": "reviewer"}'}
            ...             ],
            ...         }
            ...     )
            ...     provider.context["role"]
            'reviewer'
        """
        role = json.loads(request["messages"][-1]["content"])["role"]
        self.context = {
            "case": self.case,
            "period": request["period"],
            "agent_call_id": request["call_id"],
            "role": role,
        }

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Send one logical call and settle its cost, blocking the budget on failure.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The complete reply.

        Raises:
            ProviderError: If the attempts fail.
            RuntimeError: If the budget refuses the call or the reply is not complete.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     budget = Budget.create(Path(folder) / "budget.json", 1, 1, 5)
            ...     budget.state["logical_calls"] = 795
            ...     provider = LiveProvider(
            ...         budget,
            ...         Path(folder),
            ...         "example",  # pragma: allowlist secret
            ...     )
            ...     provider.complete([], {"max_output_tokens": 8192})
            Traceback (most recent call last):
            ...
            RuntimeError: budget: logical calls are exhausted
        """
        self.logical_call = self.budget.begin()
        try:
            reply = super().complete(messages, settings)
            write_json(
                self.folder / f"provider-reply-{self.budget.state['calls']:04d}.json",
                asdict(reply),
            )
            self.budget.settle(reply)
            if reply.completion != "complete":
                raise RuntimeError("reply: is incomplete or refused and is not retried")
        except BaseException as error:
            self.budget.block(type(error).__name__)
            raise
        return reply

    def _send_json(
        self, endpoint: str, request: dict[str, object], headers: Mapping[str, str]
    ) -> tuple[dict[str, object], str | None, HttpEvidence]:
        """Send the request with at most two attempts and give its decoded response.

        Args:
            endpoint (str): The provider endpoint.
            request (dict[str, object]): The request body.
            headers (Mapping[str, str]): The request headers.

        Returns:
            tuple[dict[str, object], str | None, HttpEvidence]: The response, its
                request identifier and its HTTP evidence.
        """
        return asyncio.run(self._exchange(endpoint, request, headers))

    async def _exchange(
        self, endpoint: str, request: JsonObject, headers: Mapping[str, str]
    ) -> tuple[dict[str, object], str | None, HttpEvidence]:
        """Send the attempts of one logical call within its deadline.

        Args:
            endpoint (str): The provider endpoint.
            request (dict[str, Any]): The request body.
            headers (Mapping[str, str]): The request headers.

        Returns:
            tuple[dict[str, object], str | None, HttpEvidence]: The response, its
                request identifier and its HTTP evidence.

        Raises:
            ProviderError: If an attempt fails and is not sent again.
            RuntimeError: If the deadline, the budget or the wait stops a retry.
        """
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        digest = hashlib.sha256(body).hexdigest()
        started = self.clock()
        for attempt_number in (1, 2):
            remaining = self.deadline_seconds - (self.clock() - started)
            if remaining <= 0:
                raise RuntimeError("request: logical deadline is exhausted")
            slot = self.budget.reserve(request, self.logical_call, attempt_number)
            record: JsonObject = {
                **slot,
                **self.context,
                "kind": "attempt-start",
                "body_sha256": digest,
                "body_bytes_received": 0,
                "utc": datetime.datetime.now(datetime.UTC).isoformat(),
            }
            write_json(
                self.folder / f"provider-request-{slot['call']:04d}.json", request
            )
            self._event(record)
            attempt_started = self.clock()
            attempt = await self._attempt(endpoint, body, headers, remaining)
            received = sum(len(chunk) for chunk in attempt.chunks)
            outcome: JsonObject = {
                **record,
                "kind": "attempt-end",
                "http_status": attempt.status,
                "body_bytes_received": received,
                "elapsed_seconds": self.clock() - attempt_started,
                "headers": attempt.headers,
                "error_kind": attempt.error_kind,
            }
            if attempt.chunks:
                outcome["response_body_base64"] = base64.b64encode(
                    b"".join(attempt.chunks)
                ).decode()
            raw: object = attempt.raw
            # The parent provider reads a successful response as it reads any other.
            if (
                attempt.error_kind is None
                and attempt.status == 200
                and isinstance(raw, dict)
                and attempt.response is not None
            ):
                outcome["classification"] = "received_response"
                self._event(outcome)
                return (
                    cast(dict[str, object], raw),
                    attempt.headers.get("x-request-id")
                    or attempt.headers.get("request-id"),
                    http_evidence(attempt.response),
                )
            retryable = is_retryable(
                attempt.status, attempt.raw, received, attempt.error_kind
            )
            outcome["retry_eligible"] = retryable
            outcome["classification"] = "retryable_error" if retryable else "stop_error"
            self._event(outcome)
            self.budget.mark_uncertain(attempt.error_kind or f"HTTP {attempt.status}")
            if not retryable or attempt_number == 2:
                raise ProviderError(
                    "provider request stopped; inspect transport-events.jsonl",
                    "timeout" if attempt.error_kind == "timeout" else "service",
                )
            if (
                self.budget.state["extra_attempts"]
                >= TRANSPORT_POLICY["max_extra_attempts"]
            ):
                raise RuntimeError("budget: extra attempts are exhausted")
            await self._wait(slot, attempt.headers.get("retry-after"), started)
        raise RuntimeError("request: attempts ended without an outcome")

    async def _attempt(
        self,
        endpoint: str,
        body: bytes,
        headers: Mapping[str, str],
        remaining: float,
    ) -> _Attempt:
        """Send one attempt and read its whole body within the remaining deadline.

        Args:
            endpoint (str): The provider endpoint.
            body (bytes): The request body.
            headers (Mapping[str, str]): The request headers.
            remaining (float): The seconds left of the logical deadline.

        Returns:
            _Attempt: The status, the body, the kept headers and any failure.
        """
        attempt = _Attempt()
        transport = (
            self.transport_factory()
            if self.transport_factory
            else httpx.AsyncHTTPTransport(retries=0)
        )
        timeout = httpx.Timeout(
            TRANSPORT_POLICY["read_timeout"],
            connect=TRANSPORT_POLICY["connect_timeout"],
            write=TRANSPORT_POLICY["write_timeout"],
            pool=TRANSPORT_POLICY["pool_timeout"],
        )
        try:
            async with (
                asyncio.timeout(remaining),
                httpx.AsyncClient(
                    timeout=timeout, transport=transport, follow_redirects=False
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    content=body,
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as exchange,
            ):
                attempt.status = exchange.status_code
                attempt.headers = {
                    key: value
                    for key, value in exchange.headers.items()
                    if key in _KEPT_HEADERS
                }
                async for chunk in exchange.aiter_raw():
                    attempt.chunks.append(chunk)
                attempt.response = httpx.Response(
                    exchange.status_code,
                    headers=exchange.headers,
                    content=b"".join(attempt.chunks),
                    request=exchange.request,
                )
                try:
                    attempt.raw = json.loads(
                        attempt.response.content, parse_float=Decimal
                    )
                except ValueError, UnicodeError:
                    attempt.raw = None
        except httpx.TimeoutException:
            attempt.error_kind = "timeout"
        except TimeoutError:
            attempt.error_kind = "logical_deadline"
        except httpx.HTTPError:
            attempt.error_kind = "transport"
        return attempt

    async def _wait(
        self, slot: JsonObject, retry_after: str | None, started: float
    ) -> None:
        """Wait before the second attempt, within the logical deadline.

        Args:
            slot (dict[str, Any]): The reservation of the failed attempt.
            retry_after (str | None): The `Retry-After` header of the failed attempt.
            started (float): The clock time the logical call started.

        Raises:
            RuntimeError: If the wait does not fit the deadline.
        """
        delay = retry_delay(retry_after, self.jitter())
        remaining = self.deadline_seconds - (self.clock() - started)
        if delay >= remaining:
            raise RuntimeError("request: retry does not fit the logical deadline")
        self._event({**slot, **self.context, "kind": "retry-wait", "seconds": delay})
        try:
            async with asyncio.timeout(remaining):
                await self.sleeper(delay)
        except TimeoutError:
            self._event(
                {
                    **slot,
                    **self.context,
                    "kind": "retry-wait-deadline",
                    "error_kind": "logical_deadline",
                }
            )
            raise RuntimeError(
                "request: logical deadline is exhausted during the retry wait"
            ) from None

    def _event(self, value: JsonObject) -> None:
        """Append one event to the transport record.

        Args:
            value (dict[str, Any]): The event.
        """
        append_json_line(self.folder / "transport-events.jsonl", value)
