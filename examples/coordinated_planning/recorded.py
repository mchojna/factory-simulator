"""The recorded provider: the saved replies of a case, given for its exact requests.

Examples:
    >>> RecordedProvider.provider
    'openai'
"""

import json
from collections.abc import Mapping
from pathlib import Path

from examples.coordinated_planning import MODEL
from examples.coordinated_planning.transport import FixedOpenAIProvider
from examples.utils.providers import ProviderReply
from factory_simulator.benchmark.client import JsonObject


class RecordedProvider(FixedOpenAIProvider):
    """The provider that gives saved replies and never opens a connection.

    Each request must equal the saved request at its position, messages included.

    Attributes:
        model (str): The requested model identifier.
        pairs (list[tuple[dict[str, Any], dict[str, Any]]]): The saved requests with
            their replies, in order.
        index (int): The number of replies given.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     _ = (Path(folder) / "model-calls.jsonl").write_text("")
        ...     RecordedProvider(Path(folder)).pairs
        []
    """

    def __init__(self, folder: Path) -> None:
        """Read the saved requests and replies of a case, without a credential.

        Args:
            folder (Path): The case folder with its `model-calls.jsonl`.

        Raises:
            ValueError: If a saved request has no reply.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     path = Path(folder) / "model-calls.jsonl"
            ...     _ = path.write_text(json.dumps({"kind": "provider-request"}))
            ...     RecordedProvider(Path(folder))
            Traceback (most recent call last):
            ...
            ValueError: model-calls.jsonl: requests and replies differ in number
        """
        # No HTTP client and no credential: the provider only reads the saved calls.
        self.model = MODEL
        events = [
            json.loads(line)
            for line in (folder / "model-calls.jsonl").read_text().splitlines()
        ]
        requests = [event for event in events if event["kind"] == "provider-request"]
        replies = [event for event in events if event["kind"] == "provider-response"]
        if len(requests) != len(replies):
            raise ValueError("model-calls.jsonl: requests and replies differ in number")
        self.pairs: list[tuple[JsonObject, JsonObject]] = list(
            zip(requests, replies, strict=True)
        )
        self.index = 0

    def complete(
        self, messages: list[dict[str, str]], settings: Mapping[str, object]
    ) -> ProviderReply:
        """Give the saved reply of the next request, when it equals the saved one.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            settings (Mapping[str, object]): The requested generation settings.

        Returns:
            ProviderReply: The saved reply.

        Raises:
            RuntimeError: If the request differs from the saved one or none is left.
            ValueError: If the saved reply belongs to another call.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     _ = (Path(folder) / "model-calls.jsonl").write_text("")
            ...     RecordedProvider(Path(folder)).complete([], {})
            Traceback (most recent call last):
            ...
            RuntimeError: model-calls.jsonl: request 1 has no saved reply
        """
        if self.index >= len(self.pairs):
            raise RuntimeError(
                f"model-calls.jsonl: request {self.index + 1} has no saved reply"
            )
        request, response = self.pairs[self.index]
        if (
            self.request_payload(messages, settings) != request["request"]
            or messages != request["messages"]
        ):
            raise RuntimeError(
                f"model-calls.jsonl: request {self.index + 1} differs from its record"
            )
        if (
            request["call_id"] != response["call_id"]
            or request["period"] != response["period"]
        ):
            raise ValueError(
                f"model-calls.jsonl: reply {self.index + 1} belongs to another call"
            )
        self.index += 1
        return ProviderReply(**response["reply"])

    def assert_complete(self) -> None:
        """Confirm that every saved reply was given.

        Raises:
            RuntimeError: If a saved reply is left.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     _ = (Path(folder) / "model-calls.jsonl").write_text("")
            ...     RecordedProvider(Path(folder)).assert_complete()
        """
        if self.index != len(self.pairs):
            raise RuntimeError(
                f"model-calls.jsonl: {len(self.pairs) - self.index} saved replies are "
                "left"
            )
