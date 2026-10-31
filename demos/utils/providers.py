"""The hosted providers: requests, responses and token counts.

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
from importlib import import_module
from typing import Any, Protocol, TypedDict, cast
from urllib.parse import quote

import httpx2 as httpx


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderReply:
    """The generated text, provider response and observed request facts.

    Attributes:
        text (str): The generated text.
        request (dict[str, object]): The effective request body.
        response (dict[str, object]): The received response body.
        requested_model (str): The requested model identifier.
        returned_model (str | None): The returned model identifier, when present.
        response_id (str | None): The response identifier, when present.
        stop_reason (str | None): The reported reason generation ended.
        input_tokens (int | None): The reported input-token count, when present.
        output_tokens (int | None): The reported output-token count, when present.
        reasoning (object | None): The reported reasoning field, when present.
        provider_revision (str | None): The returned model revision, when present.
        routing_identity (str | None): The reported provider route, when present.
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
        ...     stop_reason=None,
        ...     input_tokens=None,
        ...     output_tokens=None,
        ... )
        >>> reply.text
        'plan'
    """

    text: str
    request: dict[str, object]
    response: dict[str, object]
    requested_model: str
    returned_model: str | None
    response_id: str | None
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning: object | None = None
    provider_revision: str | None = None
    routing_identity: str | None = None
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
    """An unsuccessful provider request with its available response.

    Attributes:
        reply (ProviderReply | None): The observed response, or None before a
            response is available.

    Examples:
        >>> ProviderError("unavailable").reply is None
        True
    """

    def __init__(self, message: str, reply: ProviderReply | None = None) -> None:
        """Keep the failure message and any observed response.

        Args:
            message (str): The failure message.
            reply (ProviderReply | None, optional): The observed response, or None.

        Examples:
            >>> str(ProviderError("unavailable"))
            'unavailable'
        """
        super().__init__(message)
        self.reply = reply


class Provider(Protocol):
    """The request and token-count interface of a hosted provider.

    Attributes:
        provider (str): The provider identifier.

    Examples:
        >>> AnthropicProvider.provider
        'anthropic'
    """

    provider: str

    def count_input_tokens(self, messages: list[dict[str, str]]) -> int:
        """Count the input tokens before dispatch.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.

        Returns:
            int: The input-token estimate before dispatch.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.count_input_tokens([])
            3
        """
        ...

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
            ProviderError: If the transport fails, the response is not a JSON object
                or the status is 400 or above.
        """
        try:
            answer = self._client.post(endpoint, json=request, headers=dict(headers))
        except httpx.HTTPError as error:
            partial = _request_failure_reply(self.model, request, error)
            raise ProviderError(
                f"{self.provider} request failed: transport error", partial
            ) from error
        request_id = answer.headers.get("request-id") or answer.headers.get(
            "x-request-id"
        )
        evidence = _http_evidence(answer)
        try:
            raw = json.loads(answer.content, parse_float=Decimal, parse_int=int)
        except ValueError as error:
            partial = self._partial_reply(
                request,
                {"raw_text": answer.text},
                request_id,
                evidence,
            )
            raise ProviderError(
                f"{self.provider} response was not JSON", partial
            ) from error
        if not isinstance(raw, dict):
            partial = self._partial_reply(
                request,
                {"raw_value": raw},
                request_id,
                evidence,
            )
            raise ProviderError(
                f"{self.provider} response was not a JSON object", partial
            )
        response = cast(dict[str, object], raw)
        if answer.status_code >= 400:
            partial = self._partial_reply(request, response, request_id, evidence)
            error_kind = (
                "rate_limit"
                if answer.status_code == 429 and self.provider != "openai"
                else _provider_error_kind(response)
            )
            raise ProviderError(
                f"{self.provider} request failed: {error_kind}", partial
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
            input_tokens=None,
            output_tokens=None,
            **evidence,
        )

    def count_input_tokens(self, messages: list[dict[str, str]]) -> int:
        """Count an input-token estimate from message characters.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.

        Returns:
            int: The input-token estimate before dispatch.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.count_input_tokens([])
            3
        """
        return 3 + sum(
            3 + len(message["role"]) + len(message["content"]) for message in messages
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
        supported = {"temperature", "top_p", "max_output_tokens"}
        _refuse_unsupported_settings("OpenAI", settings, supported)
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
        choices = response.get("choices")
        choice = (
            cast(dict[str, object], choices[0])
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else {}
        )
        message = _object_field(choice, "message")
        usage = _object_field(response, "usage")
        return ProviderReply(
            text=_string_field(message, "content") or "",
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=_string_field(choice, "finish_reason"),
            input_tokens=_integer_field(usage, "prompt_tokens"),
            output_tokens=_integer_field(usage, "completion_tokens"),
            reasoning=message.get("reasoning"),
            provider_revision=_string_field(response, "system_fingerprint"),
            **evidence,
        )

    def count_input_tokens(self, messages: list[dict[str, str]]) -> int:
        """Count messages with the tokenizer of the selected model.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.

        Returns:
            int: The input-token estimate before dispatch.

        Raises:
            RuntimeError: If the optional tokenizer is not installed.
            ValueError: If the model has no known tokenizer.

        Examples:
            >>> provider = OpenAIProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> try:
            ...     provider.count_input_tokens([])
            ... except (ValueError, RuntimeError) as error:
            ...     print("token" in str(error))
            True
        """
        try:
            tiktoken: Any = import_module("tiktoken")
        except ImportError as error:
            raise RuntimeError(
                "install the provider-openai group to count tokens: "
                "bash scripts/setup_environment.sh --provider openai"
            ) from error
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError as error:
            raise ValueError(
                f"model has no declared tokenizer: {self.model}"
            ) from error
        return 3 + sum(
            3
            + len(encoding.encode(message["role"]))
            + len(encoding.encode(message["content"]))
            for message in messages
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
        supported = {"temperature", "top_p", "max_output_tokens"}
        _refuse_unsupported_settings("Anthropic", settings, supported)
        if "temperature" in settings and "top_p" in settings:
            raise ValueError("unsupported Anthropic settings: temperature and top_p")
        system = [
            message["content"] for message in messages if message["role"] == "system"
        ]
        turns = [message for message in messages if message["role"] != "system"]
        if any(message["role"] not in {"user", "assistant"} for message in turns):
            raise ValueError(
                "unsupported Anthropic messages: expected user or assistant"
            )
        request: dict[str, object] = {
            "model": self.model,
            "max_tokens": settings.get("max_output_tokens"),
            "messages": turns,
        }
        if system:
            request["system"] = "\n\n".join(system)
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
        blocks = response.get("content")
        text = "".join(_text_values(blocks, "text", "type"))
        usage = _object_field(response, "usage")
        return ProviderReply(
            text=text,
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=_string_field(response, "stop_reason"),
            input_tokens=_integer_field(usage, "input_tokens"),
            output_tokens=_integer_field(usage, "output_tokens"),
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
        supported = {"temperature", "top_p", "max_output_tokens"}
        _refuse_unsupported_settings("Google", settings, supported)
        system = [
            message["content"] for message in messages if message["role"] == "system"
        ]
        turns = [message for message in messages if message["role"] != "system"]
        contents: list[dict[str, object]] = []
        for message in turns:
            role = message["role"]
            if role not in {"user", "assistant"}:
                raise ValueError(
                    "unsupported Google messages: expected user or assistant"
                )
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": message["content"]}],
                }
            )
        generation: dict[str, object] = {}
        if "max_output_tokens" in settings:
            generation["maxOutputTokens"] = settings["max_output_tokens"]
        if "temperature" in settings:
            generation["temperature"] = settings["temperature"]
        if "top_p" in settings:
            generation["topP"] = settings["top_p"]
        request: dict[str, object] = {"contents": contents}
        if system:
            request["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
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
        candidates = response.get("candidates")
        candidate = (
            cast(dict[str, object], candidates[0])
            if isinstance(candidates, list)
            and candidates
            and isinstance(candidates[0], dict)
            else {}
        )
        content = _object_field(candidate, "content")
        parts = content.get("parts")
        text = "".join(_text_values(parts, "text"))
        usage = _object_field(response, "usageMetadata")
        return ProviderReply(
            text=text,
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "modelVersion"),
            response_id=_string_field(response, "responseId") or request_id,
            stop_reason=_string_field(candidate, "finishReason"),
            input_tokens=_integer_field(usage, "promptTokenCount"),
            output_tokens=_integer_field(usage, "candidatesTokenCount"),
            provider_revision=_string_field(response, "modelVersion"),
            **evidence,
        )


class OpenRouterProvider(_HostedProvider):
    """The OpenRouter hosted-model adapter.

    Attributes:
        model (str): The requested model identifier.
        provider (str): The provider identifier.
        endpoint (str): The model-provider HTTP endpoint.
        environment_key (str): The environment variable holding the credential.

    Examples:
        >>> OpenRouterProvider.provider
        'openrouter'
    """

    provider = "openrouter"
    environment_key = "OPENROUTER_API_KEY"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

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
            >>> provider = OpenRouterProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.request_payload([], {"max_output_tokens": 2})["max_tokens"]
            2
        """
        supported = {"temperature", "top_p", "max_output_tokens"}
        _refuse_unsupported_settings("OpenRouter", settings, supported)
        request: dict[str, object] = {"model": self.model, "messages": messages}
        if "max_output_tokens" in settings:
            request["max_tokens"] = settings["max_output_tokens"]
        request.update(
            {key: settings[key] for key in ("temperature", "top_p") if key in settings}
        )
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
            >>> provider = OpenRouterProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> provider.complete([], {"unsupported": 1})
            Traceback (most recent call last):
            ...
            ValueError: unsupported OpenRouter settings: unsupported
        """
        request = self.request_payload(messages, settings)
        response, request_id, evidence = self._send_json(
            self.endpoint,
            request,
            {
                "Authorization": f"Bearer {self._api_key}",
                "X-OpenRouter-Metadata": "enabled",
            },
        )
        choices = response.get("choices")
        choice = (
            cast(dict[str, object], choices[0])
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else {}
        )
        message = _object_field(choice, "message")
        usage = _object_field(response, "usage")
        routing = _string_field(response, "provider")
        metadata = _object_field(response, "openrouter_metadata")
        routing = routing or _string_field(metadata, "provider_name")
        return ProviderReply(
            text=_string_field(message, "content") or "",
            request=request,
            response=response,
            requested_model=self.model,
            returned_model=_string_field(response, "model"),
            response_id=_string_field(response, "id") or request_id,
            stop_reason=_string_field(choice, "finish_reason"),
            input_tokens=_integer_field(usage, "prompt_tokens"),
            output_tokens=_integer_field(usage, "completion_tokens"),
            provider_revision=_string_field(response, "system_fingerprint"),
            routing_identity=routing,
            **evidence,
        )


def _refuse_unsupported_settings(
    provider: str,
    settings: Mapping[str, object],
    supported: set[str],
) -> None:
    """Refuse generation settings that the provider does not support.

    Args:
        provider (str): The provider name in the error message.
        settings (Mapping[str, object]): The requested generation settings.
        supported (set[str]): The names of the supported settings.

    Raises:
        ValueError: If a setting is not supported.
    """
    unsupported = set(settings) - supported
    if unsupported:
        raise ValueError(
            f"unsupported {provider} settings: {', '.join(sorted(unsupported))}"
        )


def _provider_error_kind(response: Mapping[str, object]) -> str:
    """Give the kind of error a provider reports in its response body.

    Args:
        response (Mapping[str, object]): The response body.

    Returns:
        str: The `type`, `status` or `code` of the error, or `HTTP error` without one.
    """
    error = _object_field(response, "error")
    for key in ("type", "status", "code"):
        value = error.get(key)
        if isinstance(value, str):
            return value
    return "HTTP error"


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


def _text_values(
    value: object, text_key: str, kind_key: str | None = None
) -> list[str]:
    """Give the texts of a list of content blocks.

    Args:
        value (object): The list of content blocks.
        text_key (str): The name of the field that holds the text.
        kind_key (str | None, optional): The name of the field that must be `text`;
            None when not given.

    Returns:
        list[str]: The texts of the blocks, in order.
    """
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            continue
        block = cast(dict[str, object], item)
        text = _string_field(block, text_key)
        if text is None:
            continue
        if kind_key is not None and _string_field(block, kind_key) != "text":
            continue
        texts.append(text)
    return texts
