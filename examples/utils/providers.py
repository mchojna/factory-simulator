"""The hosted providers: requests, replies, completions and failures.

Examples:
    >>> OpenAIProvider.provider
    'openai'
"""

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, TypedDict, cast
from urllib.parse import quote

import httpx2 as httpx

# The common state of the stop reason of a reply.
type Completion = Literal["complete", "truncated", "refused", "other"]
# The common kinds of failure of a provider request.
type FailureKind = Literal[
    "authentication",
    "invalid_request",
    "rate_limit",
    "timeout",
    "transport",
    "service",
    "invalid_response",
]
# The kinds of failure that can succeed when the same request is sent again.
TRANSIENT_FAILURES: frozenset[FailureKind] = frozenset(
    {"rate_limit", "timeout", "transport", "service"}
)
# The generation settings every provider accepts.
_SETTINGS = frozenset({"temperature", "top_p", "max_output_tokens"})
# The common states of the stop reasons of OpenAI.
_OPENAI_COMPLETIONS: dict[str, Completion] = {
    "stop": "complete",
    "length": "truncated",
    "content_filter": "refused",
}
# The common states of the stop reasons of Anthropic.
_ANTHROPIC_COMPLETIONS: dict[str, Completion] = {
    "end_turn": "complete",
    "stop_sequence": "complete",
    "max_tokens": "truncated",
    "model_context_window_exceeded": "truncated",
    "refusal": "refused",
}
# The common states of the stop reasons and block reasons of Google.
_GOOGLE_COMPLETIONS: dict[str, Completion] = {
    "STOP": "complete",
    "MAX_TOKENS": "truncated",
    "SAFETY": "refused",
    "RECITATION": "refused",
    "BLOCKLIST": "refused",
    "PROHIBITED_CONTENT": "refused",
    "SPII": "refused",
    "IMAGE_SAFETY": "refused",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderReply:
    """The generated text, provider response and observed request facts.

    A completion is `complete` when the model ended its answer, `truncated` when the
    output or context limit cut it, `refused` when the model or a provider filter
    declined it, and `other` for every other or missing stop reason.

    Attributes:
        text (str): The generated text.
        request (dict[str, object]): The effective request body.
        response (dict[str, object]): The received response body.
        requested_model (str): The requested model identifier.
        returned_model (str | None): The returned model identifier, when present.
        response_id (str | None): The response identifier, when present.
        stop_reason (str | None): The stop reason as the provider reports it.
        completion (Literal["complete", "truncated", "refused", "other"] | None): The
            common state of the stop reason; None for a failed request.
        input_tokens (int | None): Every input token of the request, cached tokens
            included, when reported.
        output_tokens (int | None): Every generated token, reasoning tokens included,
            when reported.
        cached_input_tokens (int | None): The input tokens read from the provider
            cache, when reported.
        reasoning_tokens (int | None): The generated tokens of hidden reasoning, when
            reported.
        reasoning (object | None): The reported reasoning field, when present.
        provider_revision (str | None): The returned model revision, when present.
        http_status (int | None): The received HTTP status, when present.
        request_body_base64 (str | None): The exact request bytes encoded as base64,
            when available.
        request_body_sha256 (str | None): The SHA-256 digest of the exact request
            bytes, when available.
        response_body_base64 (str | None): The exact response bytes encoded as
            base64, when available.
        response_body_sha256 (str | None): The SHA-256 digest of the exact response
            bytes, when available.

    Examples:
        >>> reply = ProviderReply(
        ...     text="plan",
        ...     request={},
        ...     response={},
        ...     requested_model="selected-model",
        ...     returned_model=None,
        ...     response_id=None,
        ...     stop_reason="stop",
        ...     completion="complete",
        ...     input_tokens=None,
        ...     output_tokens=None,
        ... )
        >>> reply.completion
        'complete'
    """

    text: str
    request: dict[str, object]
    response: dict[str, object]
    requested_model: str
    returned_model: str | None
    response_id: str | None
    stop_reason: str | None
    completion: Completion | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    reasoning: object | None = None
    provider_revision: str | None = None
    http_status: int | None = None
    request_body_base64: str | None = None
    request_body_sha256: str | None = None
    response_body_base64: str | None = None
    response_body_sha256: str | None = None


class HttpEvidence(TypedDict):
    """The available HTTP status and exact request and response body identities.

    Attributes:
        http_status (int | None): The received HTTP status, when present.
        request_body_base64 (str | None): The exact request bytes encoded as base64,
            when available.
        request_body_sha256 (str | None): The SHA-256 digest of the exact request
            bytes, when available.
        response_body_base64 (str | None): The exact response bytes encoded as
            base64, when available.
        response_body_sha256 (str | None): The SHA-256 digest of the exact response
            bytes, when available.

    Examples:
        >>> evidence = HttpEvidence(
        ...     http_status=200,
        ...     request_body_base64=None,
        ...     request_body_sha256=None,
        ...     response_body_base64=None,
        ...     response_body_sha256=None,
        ... )
        >>> evidence["http_status"]
        200
    """

    http_status: int | None
    request_body_base64: str | None
    request_body_sha256: str | None
    response_body_base64: str | None
    response_body_sha256: str | None


class ProviderError(RuntimeError):
    """An unsuccessful provider request with its kind and available response.

    The kind is `authentication` for status 401, 402 or 403 or the error code
    `insufficient_quota`, `invalid_request` for any other status from 400 through 499
    except 408 and 429, `timeout` for status 408 or an expired request, `rate_limit` for
    any other status 429, `service` for status 500 or above, `transport` for a request
    or response that the network did not carry, and `invalid_response` for a successful
    status without a JSON object. The kinds in `TRANSIENT_FAILURES` can succeed when the
    same request is sent again.

    Attributes:
        kind (FailureKind): The common kind of the failure.
        reply (ProviderReply | None): The observed response, or None before a
            response is available.

    Examples:
        >>> ProviderError("unavailable", "service").reply is None
        True
    """

    def __init__(
        self, message: str, kind: FailureKind, reply: ProviderReply | None = None
    ) -> None:
        """Keep the failure message, its kind and any observed response.

        Args:
            message (str): The failure message.
            kind (FailureKind): The common kind of the failure.
            reply (ProviderReply | None, optional): The observed response, or None.

        Examples:
            >>> ProviderError("unavailable", "service").kind
            'service'
        """
        super().__init__(message)
        self.kind = kind
        self.reply = reply


class Provider(Protocol):
    """The request interface of a hosted provider.

    Attributes:
        provider (str): The provider identifier.

    Examples:
        >>> AnthropicProvider.provider
        'anthropic'
    """

    provider: str

    def request_payload(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> dict[str, object]:
        """Build the effective request body from messages and generation settings.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            dict[str, object]: The request body sent to the provider.

        Raises:
            ValueError: If a setting or message role is unsupported.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.request_payload([], {"max_output_tokens": 2})["max_tokens"]
            2
        """
        ...

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Send one model request and keep its text and observed response.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The generated text and available request and response facts.

        Raises:
            ValueError: If a requested generation setting is unsupported.
            ProviderError: If transport, decoding or provider execution fails.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.complete([], {"unsupported": 1})
            Traceback (most recent call last):
            ...
            ValueError: unsupported Anthropic settings: unsupported
        """
        ...


class _HostedProvider:
    """The shared credential, HTTP request and error handling of hosted providers.

    Attributes:
        model (str): The requested model identifier.
        provider (str): The provider identifier.
        environment_key (str): The environment variable holding its credential.

    Examples:
        >>> AnthropicProvider.environment_key
        'ANTHROPIC_API_KEY'
    """

    provider: str
    environment_key: str

    def __init__(
        self,
        model: str,
        *,
        timeout_seconds: float,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create the provider client with its credential and request timeout.

        Args:
            model (str): The requested model identifier.
            timeout_seconds (float): The timeout of one HTTP request in seconds.
            api_key (str | None, optional): The explicit credential; None reads the
                provider environment variable.
            transport (httpx.BaseTransport | None, optional): The HTTP transport;
                None uses the network.

        Raises:
            ValueError: If no credential is supplied or configured.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.model
            'selected-model'
        """
        credential = api_key or os.environ.get(self.environment_key)
        if not credential:
            raise ValueError(
                f"{self.environment_key} is required before provider execution"
            )
        self.model = model
        self._api_key = credential
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def _send_json(
        self,
        endpoint: str,
        request: dict[str, object],
        headers: Mapping[str, str],
    ) -> tuple[dict[str, object], str | None, HttpEvidence]:
        """Post a JSON request and give the decoded response with its evidence.

        Args:
            endpoint (str): The URL of the provider endpoint.
            request (dict[str, object]): The request body.
            headers (Mapping[str, str]): The request headers.

        Returns:
            tuple[dict[str, object], str | None, HttpEvidence]: The response body, the
                request identifier when present and the HTTP evidence.

        Raises:
            ProviderError: If the transport fails, the status is 400 or above or the
                response is not a JSON object.
        """
        try:
            exchange = self._client.post(endpoint, json=request, headers=dict(headers))
        except httpx.HTTPError as error:
            kind = (
                "timeout" if isinstance(error, httpx.TimeoutException) else "transport"
            )
            partial = _request_failure_reply(self.model, request, error)
            raise ProviderError(
                f"{self.provider} request failed: {kind}", kind, partial
            ) from error
        request_id = exchange.headers.get("request-id") or exchange.headers.get(
            "x-request-id"
        )
        evidence = _http_evidence(exchange)
        try:
            raw: object = json.loads(exchange.content, parse_float=Decimal)
        except ValueError:
            raw = None
            response: dict[str, object] = {"raw_text": exchange.text}
        else:
            response = (
                cast(dict[str, object], raw)
                if isinstance(raw, dict)
                else {"raw_value": raw}
            )
        partial = self._partial_reply(request, response, request_id, evidence)
        if exchange.status_code >= 400:
            code = _provider_error_code(response, exchange.status_code)
            kind = _status_failure_kind(exchange.status_code, code)
            raise ProviderError(
                f"{self.provider} request failed: {kind} ({code})", kind, partial
            )
        if not isinstance(raw, dict):
            raise ProviderError(
                f"{self.provider} response was not a JSON object",
                "invalid_response",
                partial,
            )
        return response, request_id, evidence

    def _partial_reply(
        self,
        request: dict[str, object],
        response: dict[str, object],
        request_id: str | None,
        evidence: HttpEvidence,
    ) -> ProviderReply:
        """Give the reply of a failed request, with an empty text.

        Args:
            request (dict[str, object]): The request body.
            response (dict[str, object]): The received response body.
            request_id (str | None): The request identifier, when present.
            evidence (HttpEvidence): The HTTP evidence of the exchange.

        Returns:
            ProviderReply: The reply with the observed request and response facts.
        """
        return ProviderReply(
            text="",
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=None,
            completion=None,
            input_tokens=None,
            output_tokens=None,
            **evidence,
        )


class OpenAIProvider(_HostedProvider):
    """The OpenAI hosted-model adapter.

    Attributes:
        model (str): The requested model identifier.
        provider (str): The provider identifier.
        endpoint (str): The model-provider HTTP endpoint.
        environment_key (str): The environment variable holding the credential.

    Examples:
        >>> OpenAIProvider.provider
        'openai'
    """

    provider = "openai"
    environment_key = "OPENAI_API_KEY"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def request_payload(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> dict[str, object]:
        """Build the effective request body from messages and generation settings.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            dict[str, object]: The request body sent to the provider.

        Raises:
            ValueError: If a setting or message role is unsupported.

        Examples:
            >>> provider = OpenAIProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> request = provider.request_payload([], {"max_output_tokens": 2})
            >>> request["max_completion_tokens"]
            2
        """
        _refuse_unsupported_settings("OpenAI", settings)
        request: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            **dict(settings),
        }
        request["max_completion_tokens"] = request.pop("max_output_tokens")
        return request

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Send one model request and keep its text and observed response.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The generated text and available request and response facts.

        Raises:
            ValueError: If a requested generation setting is unsupported.
            ProviderError: If transport, decoding or provider execution fails.

        Examples:
            >>> provider = OpenAIProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.complete([], {"unsupported": 1})
            Traceback (most recent call last):
            ...
            ValueError: unsupported OpenAI settings: unsupported
        """
        request = self.request_payload(messages, settings)
        response, request_id, evidence = self._send_json(
            self.endpoint, request, {"Authorization": f"Bearer {self._api_key}"}
        )
        choice = _first_object(response.get("choices"))
        message = _object_field(choice, "message")
        usage = _object_field(response, "usage")
        stop_reason = _string_field(choice, "finish_reason")
        completion = (
            "refused"
            if _string_field(message, "refusal")
            else _OPENAI_COMPLETIONS.get(stop_reason or "", "other")
        )
        return ProviderReply(
            text=_string_field(message, "content") or "",
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=stop_reason,
            completion=completion,
            input_tokens=_integer_field(usage, "prompt_tokens"),
            output_tokens=_integer_field(usage, "completion_tokens"),
            cached_input_tokens=_integer_field(
                _object_field(usage, "prompt_tokens_details"), "cached_tokens"
            ),
            reasoning_tokens=_integer_field(
                _object_field(usage, "completion_tokens_details"), "reasoning_tokens"
            ),
            reasoning=message.get("reasoning"),
            provider_revision=_string_field(response, "system_fingerprint"),
            **evidence,
        )


class AnthropicProvider(_HostedProvider):
    """The Anthropic hosted-model adapter.

    Attributes:
        model (str): The requested model identifier.
        provider (str): The provider identifier.
        endpoint (str): The model-provider HTTP endpoint.
        environment_key (str): The environment variable holding the credential.

    Examples:
        >>> AnthropicProvider.provider
        'anthropic'
    """

    provider = "anthropic"
    environment_key = "ANTHROPIC_API_KEY"
    endpoint = "https://api.anthropic.com/v1/messages"

    def request_payload(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> dict[str, object]:
        """Build the effective request body from messages and generation settings.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            dict[str, object]: The request body sent to the provider.

        Raises:
            ValueError: If a setting or message role is unsupported.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.request_payload([], {"max_output_tokens": 2})["max_tokens"]
            2
        """
        _refuse_unsupported_settings("Anthropic", settings)
        if "temperature" in settings and "top_p" in settings:
            raise ValueError("unsupported Anthropic settings: temperature and top_p")
        system, turns = _split_system("Anthropic", messages)
        request: dict[str, object] = {
            "model": self.model,
            "max_tokens": settings.get("max_output_tokens"),
            "messages": turns,
        }
        if system:
            request["system"] = system
        for key in ("temperature", "top_p"):
            if key in settings:
                request[key] = settings[key]
        return request

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Send one model request and keep its text and observed response.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The generated text and available request and response facts.

        Raises:
            ValueError: If a requested generation setting is unsupported.
            ProviderError: If transport, decoding or provider execution fails.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.complete([], {"unsupported": 1})
            Traceback (most recent call last):
            ...
            ValueError: unsupported Anthropic settings: unsupported
        """
        request = self.request_payload(messages, settings)
        response, request_id, evidence = self._send_json(
            self.endpoint,
            request,
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        text = "".join(
            _string_field(block, "text") or ""
            for block in _object_items(response.get("content"))
            if block.get("type") == "text"
        )
        usage = _object_field(response, "usage")
        stop_reason = _string_field(response, "stop_reason")
        # Anthropic counts cache reads and cache writes apart from the other input.
        uncached = _integer_field(usage, "input_tokens")
        cache_read = _integer_field(usage, "cache_read_input_tokens")
        cache_write = _integer_field(usage, "cache_creation_input_tokens")
        return ProviderReply(
            text=text,
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=stop_reason,
            completion=_ANTHROPIC_COMPLETIONS.get(stop_reason or "", "other"),
            input_tokens=(
                None
                if uncached is None
                else uncached + (cache_read or 0) + (cache_write or 0)
            ),
            output_tokens=_integer_field(usage, "output_tokens"),
            cached_input_tokens=cache_read,
            **evidence,
        )


class GoogleProvider(_HostedProvider):
    """The Google hosted-model adapter.

    Attributes:
        model (str): The requested model identifier.
        provider (str): The provider identifier.
        endpoint (str): The model-provider HTTP endpoint.
        environment_key (str): The environment variable holding the credential.

    Examples:
        >>> GoogleProvider.provider
        'google'
    """

    provider = "google"
    environment_key = "GOOGLE_API_KEY"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/"

    def request_payload(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> dict[str, object]:
        """Build the effective request body from messages and generation settings.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            dict[str, object]: The request body sent to the provider.

        Raises:
            ValueError: If a setting or message role is unsupported.

        Examples:
            >>> provider = GoogleProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> request = provider.request_payload([], {"max_output_tokens": 2})
            >>> request["generationConfig"]["maxOutputTokens"]
            2
        """
        _refuse_unsupported_settings("Google", settings)
        system, turns = _split_system("Google", messages)
        contents: list[dict[str, object]] = [
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in turns
        ]
        generation: dict[str, object] = {}
        if "max_output_tokens" in settings:
            generation["maxOutputTokens"] = settings["max_output_tokens"]
        if "temperature" in settings:
            generation["temperature"] = settings["temperature"]
        if "top_p" in settings:
            generation["topP"] = settings["top_p"]
        request: dict[str, object] = {"contents": contents}
        if system:
            request["systemInstruction"] = {"parts": [{"text": system}]}
        if generation:
            request["generationConfig"] = generation
        return request

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Send one model request and keep its text and observed response.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The generated text and available request and response facts.

        Raises:
            ValueError: If a requested generation setting is unsupported.
            ProviderError: If transport, decoding or provider execution fails.

        Examples:
            >>> provider = GoogleProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.complete([], {"unsupported": 1})
            Traceback (most recent call last):
            ...
            ValueError: unsupported Google settings: unsupported
        """
        request = self.request_payload(messages, settings)
        model_path = quote(self.model, safe="-_.")
        response, request_id, evidence = self._send_json(
            f"{self.endpoint}{model_path}:generateContent",
            request,
            {"x-goog-api-key": self._api_key},
        )
        candidate = _first_object(response.get("candidates"))
        parts = _object_field(candidate, "content").get("parts")
        text = "".join(
            _string_field(part, "text") or ""
            for part in _object_items(parts)
            if part.get("thought") is not True
        )
        usage = _object_field(response, "usageMetadata")
        # A prompt blocked before generation has a block reason and no candidate.
        stop_reason = _string_field(candidate, "finishReason") or _string_field(
            _object_field(response, "promptFeedback"), "blockReason"
        )
        # Google counts the tokens of thoughts apart from the answer.
        answer_tokens = _integer_field(usage, "candidatesTokenCount")
        thought_tokens = _integer_field(usage, "thoughtsTokenCount")
        return ProviderReply(
            text=text,
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "modelVersion"),
            response_id=_string_field(response, "responseId") or request_id,
            stop_reason=stop_reason,
            completion=_GOOGLE_COMPLETIONS.get(stop_reason or "", "other"),
            input_tokens=_integer_field(usage, "promptTokenCount"),
            output_tokens=(
                None
                if answer_tokens is None and thought_tokens is None
                else (answer_tokens or 0) + (thought_tokens or 0)
            ),
            cached_input_tokens=_integer_field(usage, "cachedContentTokenCount"),
            reasoning_tokens=thought_tokens,
            provider_revision=_string_field(response, "modelVersion"),
            **evidence,
        )


def _refuse_unsupported_settings(provider: str, settings: Mapping[str, object]) -> None:
    """Refuse generation settings that the providers do not support.

    Args:
        provider (str): The provider name in the error message.
        settings (Mapping[str, object]): The requested generation settings.

    Raises:
        ValueError: If a setting is not supported.
    """
    unsupported = set(settings) - _SETTINGS
    if unsupported:
        raise ValueError(
            f"unsupported {provider} settings: {', '.join(sorted(unsupported))}"
        )


def _split_system(
    provider: str, messages: list[dict[str, str]]
) -> tuple[str, list[dict[str, str]]]:
    """Give the joined system messages and the turns of the conversation apart.

    Args:
        provider (str): The provider name in the error message.
        messages (list[dict[str, str]]): The messages, in sending order.

    Returns:
        tuple[str, list[dict[str, str]]]: The system messages joined by a blank line,
            empty without one, and the user and assistant turns in order.

    Raises:
        ValueError: If a message has a role other than system, user or assistant.
    """
    system = [message["content"] for message in messages if message["role"] == "system"]
    turns = [message for message in messages if message["role"] != "system"]
    if any(message["role"] not in {"user", "assistant"} for message in turns):
        raise ValueError(f"unsupported {provider} messages: expected user or assistant")
    return "\n\n".join(system), turns


def _status_failure_kind(status: int, code: str) -> FailureKind:
    """Give the common kind of failure of an HTTP status of 400 or above.

    Args:
        status (int): The received HTTP status.
        code (str): The error code the provider reports.

    Returns:
        FailureKind: The kind of failure the status and the code report.
    """
    if status in {401, 402, 403} or code == "insufficient_quota":
        return "authentication"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "service"
    return "invalid_request"


def _provider_error_code(response: Mapping[str, object], status: int) -> str:
    """Give the error code a provider reports in its response body.

    Args:
        response (Mapping[str, object]): The response body.
        status (int): The received HTTP status.

    Returns:
        str: The `type`, `status` or `code` of the error, or `HTTP <status>` without
            one.
    """
    error = _object_field(response, "error")
    for key in ("type", "status", "code"):
        value = error.get(key)
        if isinstance(value, str):
            return value
    return f"HTTP {status}"


def _http_evidence(response: httpx.Response) -> HttpEvidence:
    """Give the status and the exact request and response bodies of an exchange.

    Args:
        response (httpx.Response): The received response.

    Returns:
        HttpEvidence: The status, the bodies as base64 and their SHA-256 digests.
    """
    request_body = response.request.content
    response_body = response.content
    return {
        "http_status": response.status_code,
        "request_body_base64": base64.b64encode(request_body).decode("ascii"),
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "response_body_base64": base64.b64encode(response_body).decode("ascii"),
        "response_body_sha256": hashlib.sha256(response_body).hexdigest(),
    }


def _request_failure_reply(
    model: str, request: dict[str, object], error: httpx.HTTPError
) -> ProviderReply:
    """Give the reply of a request that failed before any response.

    Args:
        model (str): The requested model identifier.
        request (dict[str, object]): The request body.
        error (httpx.HTTPError): The transport error.

    Returns:
        ProviderReply: The reply with the sent request bytes when available.
    """
    sent_request = getattr(error, "request", None)
    evidence: HttpEvidence = {
        "http_status": None,
        "request_body_base64": None,
        "request_body_sha256": None,
        "response_body_base64": None,
        "response_body_sha256": None,
    }
    if isinstance(sent_request, httpx.Request):
        body = sent_request.content
        evidence["request_body_base64"] = base64.b64encode(body).decode("ascii")
        evidence["request_body_sha256"] = hashlib.sha256(body).hexdigest()
    return ProviderReply(
        text="",
        request=request,
        response={},
        requested_model=model,
        returned_model=None,
        response_id=None,
        stop_reason=None,
        completion=None,
        input_tokens=None,
        output_tokens=None,
        **evidence,
    )


def _object_field(value: Mapping[str, object], key: str) -> dict[str, object]:
    """Give a field that holds an object.

    Args:
        value (Mapping[str, object]): The object that holds the field.
        key (str): The name of the field.

    Returns:
        dict[str, object]: The field, or an empty object when it is not an object.
    """
    field = value.get(key)
    return cast(dict[str, object], field) if isinstance(field, dict) else {}


def _string_field(value: Mapping[str, object], key: str) -> str | None:
    """Give a field that holds a string.

    Args:
        value (Mapping[str, object]): The object that holds the field.
        key (str): The name of the field.

    Returns:
        str | None: The field, or None when it is not a string.
    """
    field = value.get(key)
    return field if isinstance(field, str) else None


def _integer_field(value: Mapping[str, object], key: str) -> int | None:
    """Give a field that holds an integer.

    Args:
        value (Mapping[str, object]): The object that holds the field.
        key (str): The name of the field.

    Returns:
        int | None: The field, or None when it is not an integer.
    """
    field = value.get(key)
    return field if isinstance(field, int) and not isinstance(field, bool) else None


def _object_items(value: object) -> list[dict[str, object]]:
    """Give the objects of a list.

    Args:
        value (object): The list.

    Returns:
        list[dict[str, object]]: The items that are objects, in order, or an empty list
            when the value is not a list.
    """
    if not isinstance(value, list):
        return []
    return [
        cast(dict[str, object], item)
        for item in cast(list[object], value)
        if isinstance(item, dict)
    ]


def _first_object(value: object) -> dict[str, object]:
    """Give the first item of a list when it is an object.

    Args:
        value (object): The list.

    Returns:
        dict[str, object]: The first item, or an empty object when the value is not a
            list or its first item is not an object.
    """
    if not isinstance(value, list) or not value:
        return {}
    first = cast(list[object], value)[0]
    return cast(dict[str, object], first) if isinstance(first, dict) else {}
