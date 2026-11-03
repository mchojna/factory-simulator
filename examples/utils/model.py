"""The model examples: live decisions, bounded calls and saved comparisons.

Examples:
    >>> parser = model_example_parser("planning")
    >>> parser.parse_args(["--provider", "openai", "--model", "selected"]).seed
    7
"""

import argparse
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import cast

import httpx2 as httpx
from pydantic import TypeAdapter

from examples import DEFAULT_SEED
from examples.utils import DEFAULT_SERVER
from examples.utils.cli import REPOSITORY, save_finished_run
from examples.utils.client import read_fixture
from examples.utils.providers import (
    TRANSIENT_FAILURES,
    AnthropicProvider,
    GoogleProvider,
    OpenAIProvider,
    Provider,
    ProviderError,
)
from factory_simulator.api.schemas.run import DecisionCreate
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.optimizers.myopic import myopic_optimizer
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions

_PROVIDER_CLASSES = {
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai": OpenAIProvider,
}
_DECISIONS = TypeAdapter(list[DecisionCreate])
_SYSTEM = (
    "Operate the factory for terminal profit using only the supplied public facts. "
    "A list of decisions is a JSON array matching this schema: "
    + json.dumps(_DECISIONS.json_schema(), separators=(",", ":"))
)
# The answer format each strategy asks for.
_ANSWERS = {
    "single_prompt": "Return only the JSON array of decisions.",
    "coordinated": "Return only the JSON array of decisions.",
    "tools_memory": (
        "Your reply in every turn is plain text holding one JSON object in one of "
        "four forms, and nothing else. Form one, "
        '{"kind":"read_current","fields":[...]}, asks the user for fields of the '
        'observation. Form two, {"kind":"read_description","fields":[...]}, asks for '
        "fields of the description. A form holds at most eight fields. Form three, "
        '{"kind":"check_decisions","decisions":[...]}, asks the user to check '
        'candidate decisions. Form four, {"kind":"final","decisions":[...]}, is the '
        "final answer. There are at most four turns, the final answer included. No "
        "functions are available."
    ),
}
_STRATEGY_CALLS = {"single_prompt": 2, "tools_memory": 4, "coordinated": 6}
_HORIZON = 3
_MAX_INPUT_WORDS = 16384
_MAX_OUTPUT_TOKENS = 4096
_TIMEOUT_SECONDS = 120.0


@dataclass(slots=True, kw_only=True)
class ModelAgent:
    """A model agent with bounded requests and memory of closed outcomes.

    Attributes:
        provider (Provider): The hosted provider.
        strategy (str): The selected decision procedure.
        settings (dict[str, object]): The generation and call limits.
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            feasibility check of the current run.
        folder (Path): The directory of the call record.
        memory (list[dict[str, Any]], optional): The last two closed-period
            summaries.
        calls (int, optional): The number of provider requests dispatched.
        period_calls (int, optional): The provider requests dispatched in the
            current period.

    Examples:
        >>> provider = AnthropicProvider(
        ...     "selected-model",
        ...     timeout_seconds=1,
        ...     api_key="example",  # pragma: allowlist secret
        ... )
        >>> agent = ModelAgent(
        ...     provider=provider,
        ...     strategy="single_prompt",
        ...     settings={"max_input_words": 1},
        ...     check=lambda period, decisions: [],
        ...     folder=Path("."),
        ... )
        >>> agent.calls
        0
    """

    provider: Provider
    strategy: str
    settings: dict[str, object]
    check: benchmark.Check
    folder: Path
    memory: list[JsonObject] = field(default_factory=list[JsonObject])
    calls: int = 0
    period_calls: int = 0

    def record_event(self, kind: str, content: JsonObject) -> None:
        """Record an observed request, response or outcome in the example folder.

        Args:
            kind (str): The event kind.
            content (dict[str, Any]): The observed event fields.

        Examples:
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as folder:
            ...     agent = ModelAgent(
            ...         provider=AnthropicProvider(
            ...             "selected-model",
            ...             timeout_seconds=1,
            ...             api_key="example",  # pragma: allowlist secret
            ...         ),
            ...         strategy="single_prompt",
            ...         settings={},
            ...         check=lambda period, decisions: [],
            ...         folder=Path(folder),
            ...     )
            ...     agent.record_event("closed-period", {"period": 1})
            ...     record = (Path(folder) / "model-calls.jsonl").read_text()
            ...     json.loads(record)["period"]
            1
        """
        with (self.folder / "model-calls.jsonl").open("a") as stream:
            stream.write(_payload_text({"kind": kind, **content}) + "\n")

    def _generate_text(self, messages: list[dict[str, str]], period: int) -> str:
        """Send a real provider request and give its text, recording every attempt.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            period (int): The period of the request.

        Returns:
            str: The generated text.

        Raises:
            ValueError: If input exceeds the word limit or the reply is not complete.
            RuntimeError: If the call budget is exhausted or no reply is available.
            ProviderError: If the failure is not transient or the retries run out.
        """
        words = sum(len(message["content"].split()) for message in messages)
        if words > cast(int, self.settings["max_input_words"]):
            raise ValueError("model input exceeds max_input_words")
        generation = {"max_output_tokens": self.settings["max_output_tokens"]}
        for retry in range(cast(int, self.settings["retries"]) + 1):
            if self.period_calls >= cast(int, self.settings["period_calls"]):
                raise RuntimeError("model period call budget exhausted")
            self.period_calls += 1
            self.calls += 1
            identity = {"call_id": self.calls, "period": period}
            self.record_event(
                "provider-request",
                {
                    **identity,
                    "messages": messages,
                    "request": self.provider.request_payload(messages, generation),
                },
            )
            started = time.perf_counter()
            try:
                reply = self.provider.complete(messages, generation)
            except ProviderError as error:
                self.record_event(
                    "provider-error",
                    {
                        **identity,
                        "error": str(error),
                        "failure": error.kind,
                        "reply": asdict(error.reply) if error.reply else None,
                    },
                )
                if (
                    error.kind not in TRANSIENT_FAILURES
                    or retry == self.settings["retries"]
                ):
                    raise
            else:
                self.record_event(
                    "provider-response",
                    {
                        **identity,
                        "reply": asdict(reply),
                        "elapsed_seconds": time.perf_counter() - started,
                    },
                )
                if reply.completion != "complete":
                    raise ValueError(
                        f"model reply is {reply.completion} with stop reason "
                        f"{reply.stop_reason}; inspect model-calls.jsonl"
                    )
                return reply.text
        raise RuntimeError("provider returned no response")

    def __call__(
        self, description: JsonObject, observation: JsonObject
    ) -> list[JsonObject]:
        """Choose and check the decisions of one period.

        Args:
            description (dict[str, Any]): The description of the run.
            observation (dict[str, Any]): The observation of the period.

        Returns:
            list[dict[str, Any]]: The decisions returned by the model and accepted by
                the check.

        Raises:
            ValueError: If input, model output or decisions violate their limits, or
                a reply is not complete.
            RuntimeError: If the model exhausts its call budget without a final plan.
            ProviderError: If the failure is not transient or the retries run out.

        Examples:
            >>> provider = AnthropicProvider(
            ...     "selected-model",
            ...     timeout_seconds=1,
            ...     api_key="example",  # pragma: allowlist secret
            ... )
            >>> agent = ModelAgent(
            ...     provider=provider,
            ...     strategy="single_prompt",
            ...     settings={"max_input_words": 1},
            ...     check=lambda period, decisions: [],
            ...     folder=Path("."),
            ... )
            >>> agent({}, {"period": 1})
            Traceback (most recent call last):
            ...
            ValueError: model input exceeds max_input_words
        """
        self.period_calls = 0
        period = int(observation["period"])
        context: JsonObject = {"description": description, "observation": observation}
        if self.strategy != "single_prompt":
            context["closed_periods"] = self.memory
        system = f"{_SYSTEM} {_ANSWERS[self.strategy]}"
        if self.strategy == "tools_memory":
            system += (
                f" Fields of the observation: {', '.join(sorted(observation))}."
                f" Fields of the description: {', '.join(sorted(description))}."
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": _payload_text(context)},
        ]
        if self.strategy == "tools_memory":
            decisions = self._decide_with_tools(messages, description, observation)
        elif self.strategy == "coordinated":
            decisions = self._decide_with_roles(messages, period)
        else:
            text = self._generate_text(messages, period)
            decisions = _decisions_of(_json_at_end(text))
        outcomes = self.check(period, decisions)
        self.record_event(
            "decision-check",
            {"period": period, "decisions": decisions, "outcomes": outcomes},
        )
        if any(not outcome["accepted"] for outcome in outcomes):
            raise ValueError(
                "model proposed infeasible decisions; inspect model-calls.jsonl"
            )
        return decisions

    def _decide_with_tools(
        self,
        messages: list[dict[str, str]],
        description: JsonObject,
        observation: JsonObject,
    ) -> list[JsonObject]:
        """Give the final decisions after at most four turns of reads and checks.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            description (dict[str, Any]): The description of the run.
            observation (dict[str, Any]): The observation of the period.

        Returns:
            list[dict[str, Any]]: The final decisions of the model.

        Raises:
            ValueError: If a model tool request is invalid.
            RuntimeError: If no final plan arrives within four turns.
        """
        period = int(observation["period"])
        for _ in range(4):
            text = self._generate_text(messages, period)
            value = _json_at_end(text)
            if not isinstance(value, dict):
                raise ValueError("tool response must be a JSON object")
            value = cast(JsonObject, value)
            kind = value.get("kind")
            if kind == "final":
                return _decisions_of(value.get("decisions"))
            if kind == "check_decisions":
                decisions = _decisions_of(value.get("decisions"))
                result: object = self.check(period, decisions)
            elif kind in {"read_current", "read_description"}:
                fields = value.get("fields")
                if (
                    not isinstance(fields, list)
                    or not all(
                        isinstance(key, str) for key in cast(list[object], fields)
                    )
                    or len(cast(list[object], fields)) > 8
                ):
                    raise ValueError(
                        "tool fields must contain at most eight field names"
                    )
                source = observation if kind == "read_current" else description
                result = {
                    key: source[key] for key in cast(list[str], fields) if key in source
                }
            else:
                raise ValueError("unsupported model tool")
            self.record_event(
                "tool-result", {"period": period, "request": value, "result": result}
            )
            messages.extend(
                [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": _payload_text({"result": result})},
                ]
            )
        raise RuntimeError("model tool budget exhausted without a final plan")

    def _decide_with_roles(
        self, messages: list[dict[str, str]], period: int
    ) -> list[JsonObject]:
        """Give the plan a model reviewer makes of the planner and procurement plans.

        Args:
            messages (list[dict[str, str]]): The messages, in sending order.
            period (int): The period of the decisions.

        Returns:
            list[dict[str, Any]]: The final decisions of the reviewer.

        Raises:
            ValueError: If a role proposes decisions outside its responsibility.
        """
        proposals: list[JsonObject] = []
        for role, allowed in [
            ("planner", {"ship", "cancel", "transfer", "repair", "produce"}),
            ("procurement", {"buy"}),
        ]:
            context = {
                "role": role,
                "allowed_kinds": sorted(allowed),
                "earlier_proposals": proposals,
            }
            text = self._generate_text(
                [*messages, {"role": "user", "content": _payload_text(context)}], period
            )
            decisions = _decisions_of(_json_at_end(text))
            if any(decision["kind"] not in allowed for decision in decisions):
                raise ValueError(
                    f"{role} proposed a decision outside its responsibility"
                )
            proposals.extend(decisions)
        context = {
            "role": "reviewer",
            "proposal": proposals,
            "checks": self.check(period, proposals),
            "instruction": "Return the complete final JSON decision array.",
        }
        text = self._generate_text(
            [*messages, {"role": "user", "content": _payload_text(context)}], period
        )
        return _decisions_of(_json_at_end(text))


def _payload_text(value: object) -> str:
    """Give the JSON text of a value, with exact decimals written as text.

    Args:
        value (object): The value to serialize.

    Returns:
        str: JSON with sorted keys, a space after every comma and colon, and decimal
            values preserved as text.
    """
    # The spaces make every key and value one word of the input limit.
    return json.dumps(value, default=str, sort_keys=True)


def _json_at_end(text: str) -> object:
    """Give the JSON value that ends a model reply.

    Args:
        text (str): The text of a model reply.

    Returns:
        object: The first JSON array or object followed by nothing but whitespace and
            the backticks of a Markdown code block.

    Raises:
        ValueError: If no JSON array or object ends the reply.
    """
    decoder = json.JSONDecoder(parse_float=Decimal)
    for start, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if not text[end:].replace("`", "").strip():
            return value
    raise ValueError("model reply does not end with a JSON value")


def _decisions_of(value: object) -> list[JsonObject]:
    """Give the model decisions validated against the HTTP input schema.

    Args:
        value (object): The decisions the model returned.

    Returns:
        list[dict[str, Any]]: The validated decisions with their supplied numeric
            values.

    Raises:
        ValueError: If a decision does not match the HTTP input schema.
    """
    _DECISIONS.validate_python(value)
    return cast(list[JsonObject], value)


def run_model(
    client: httpx.Client,
    example_name: str,
    strategy: str,
    provider: str,
    model: str,
    seed: int,
    output: Path,
    *,
    max_input_words: int = _MAX_INPUT_WORDS,
    max_output_tokens: int = _MAX_OUTPUT_TOKENS,
    timeout_seconds: float = _TIMEOUT_SECONDS,
    retries: int = 0,
    adapter: Provider | None = None,
) -> Path:
    """Run one model, the myopic optimizer and no decisions on one small world.

    Args:
        client (httpx.Client): The client of the HTTP interface.
        example_name (str): The name of the example.
        strategy (str): The model strategy: single_prompt, tools_memory or
            coordinated.
        provider (str): The hosted-provider identifier.
        model (str): The requested model identifier.
        seed (int): The seed of every compared run.
        output (Path): The root output directory.
        max_input_words (int, optional): The maximum number of input words per
            request.
        max_output_tokens (int, optional): The maximum requested output tokens per
            response.
        timeout_seconds (float, optional): The timeout of one provider request in
            seconds.
        retries (int, optional): The maximum retries of a rate limit, timeout,
            transport failure or provider service failure per generated response.
        adapter (Provider | None, optional): An opened provider; None creates the
            selected provider.

    Returns:
        Path: The completed example summary beside the model-call record and the
            exports of the runs.

    Raises:
        ValueError: If configuration, model output or candidate decisions are
            invalid, or a reply is not complete.
        ProviderError: If the failure is not transient or the retries run out.
        RuntimeError: If a provider budget is exhausted or the HTTP interface
            refuses a request.

    Examples:
        >>> with httpx.Client(base_url="http://localhost/api/v1") as client:
        ...     run_model(
        ...         client,
        ...         "example",
        ...         "unknown",
        ...         "openai",
        ...         "selected-model",
        ...         7,
        ...         Path("data/examples"),
        ...     )
        Traceback (most recent call last):
        ...
        ValueError: unsupported language-model strategy: unknown
    """
    settings = method_settings(
        strategy,
        provider,
        model,
        max_input_words=max_input_words,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    hosted = adapter or _PROVIDER_CLASSES[provider](
        model, timeout_seconds=timeout_seconds
    )
    folder = output / f"{example_name}-{uuid.uuid4().hex[:12]}"
    folder.mkdir(parents=True, exist_ok=False)
    manifest = benchmark.send(
        client, "POST", "/manifests", read_fixture("manifest.json")
    )
    scenario = benchmark.send(
        client,
        "POST",
        f"/manifests/{manifest['id']}/scenarios",
        read_fixture("scenario.json"),
    )
    run = benchmark.start_run(client, scenario["id"], seed)
    agent = ModelAgent(
        provider=hosted,
        strategy=strategy,
        settings=settings,
        check=partial(benchmark.create_check, client, str(run["id"])),
        folder=folder,
    )
    rows = {
        strategy: _play_run(client, example_name, run, agent, folder / strategy, agent)
    }
    for method in ("myopic", "no_decisions"):
        run = benchmark.start_run(client, scenario["id"], seed)
        check = partial(benchmark.create_check, client, str(run["id"]))
        controller = myopic_optimizer(check) if method == "myopic" else no_decisions
        rows[method] = _play_run(client, example_name, run, controller, folder / method)
    path = folder / "example-summary.json"
    path.write_text(
        json.dumps(
            {
                "example": example_name,
                "strategy": strategy,
                "provider": provider,
                "model": model,
                "seed": seed,
                "settings": settings,
                "methods": rows,
                "provider_calls": agent.calls,
                "monetary_spend": None,
            },
            default=str,
            indent=2,
        )
        + "\n"
    )
    return path


def _play_run(
    client: httpx.Client,
    example_name: str,
    run: JsonObject,
    controller: benchmark.Agent,
    folder: Path,
    agent: ModelAgent | None = None,
) -> JsonObject:
    """Play a run, keep the closed periods in the memory of the agent and save it.

    Args:
        client (httpx.Client): The client of the HTTP interface.
        example_name (str): The name of the example.
        run (dict[str, Any]): The start response of the run.
        controller (Agent): The agent that decides each period.
        folder (Path): The output directory of the run.
        agent (ModelAgent | None, optional): The model agent whose memory and call
            record take the closed periods; None when not given.

    Returns:
        dict[str, Any]: The run identifier, the profit and the path of the summary.

    Raises:
        RuntimeError: If the HTTP interface refuses a request.
    """
    answer = run
    while not answer.get("finished", False):
        observation = benchmark.read(client, f"/runs/{run['id']}/observation")
        decisions = controller(run["description"], observation)
        answer = benchmark.send(
            client,
            "POST",
            f"/runs/{run['id']}/decisions",
            {"period": observation["period"], "decisions": decisions},
        )
        if agent is not None:
            closed = benchmark.read(client, f"/runs/{run['id']}/periods")["periods"][-1]
            agent.record_event("closed-period", closed)
            state = closed["steps"][-1]["state"]
            memory = {
                "period": closed["period"],
                "cash": state["cash"],
                "stock": state["stock"],
                "outcomes": next(
                    step["outcomes"]
                    for step in closed["steps"]
                    if step["step"] == "execute_decisions"
                ),
            }
            agent.memory = [*agent.memory, memory][-2:]
    result = benchmark.read(client, f"/runs/{run['id']}/result")
    record = save_finished_run(client, example_name, run, result, folder)
    return {"run_id": run["id"], "profit": result["profit"], "record": str(record)}


def model_example_parser(example_name: str) -> argparse.ArgumentParser:
    """Build the command parser with an explicit model and bounded request settings.

    `--provider` and `--model` take their defaults from the environment variables
    `MODEL_PROVIDER` and `MODEL_NAME`. Each is required when its variable is not set.

    Args:
        example_name (str): The name of the example command.

    Returns:
        argparse.ArgumentParser: The parser for the model, provider, server, seed,
            limits and output.

    Examples:
        >>> parser = model_example_parser("planning")
        >>> parser.parse_args(["--provider", "google", "--model", "selected"]).provider
        'google'
    """
    provider = os.environ.get("MODEL_PROVIDER") or None
    model = os.environ.get("MODEL_NAME") or None
    parser = argparse.ArgumentParser(prog=example_name)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--output", type=Path, default=REPOSITORY / "data" / "examples" / example_name
    )
    parser.add_argument(
        "--provider",
        choices=sorted(_PROVIDER_CLASSES),
        default=provider,
        required=provider is None,
    )
    parser.add_argument("--model", default=model, required=model is None)
    parser.add_argument("--max-input-words", type=int, default=_MAX_INPUT_WORDS)
    parser.add_argument("--max-output-tokens", type=int, default=_MAX_OUTPUT_TOKENS)
    parser.add_argument("--timeout-seconds", type=float, default=_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, choices=range(3), default=0)
    return parser


def run_model_command(
    example_name: str, strategy: str, arguments: list[str] | None = None
) -> None:
    """Run the model example selected by the command arguments.

    Args:
        example_name (str): The name of the example command.
        strategy (str): The selected decision procedure.
        arguments (list[str] | None, optional): The command arguments; None reads
            the process arguments.

    Raises:
        ValueError: If a model setting or required provider credential is invalid.

    Examples:
        >>> arguments = ["--provider", "openai", "--model", "selected-model"]
        >>> run_model_command("planning", "unknown", arguments)
        Traceback (most recent call last):
        ...
        ValueError: unsupported language-model strategy: unknown
    """
    options = model_example_parser(example_name).parse_args(arguments)
    with httpx.Client(base_url=options.server, timeout=120) as client:
        print(
            run_model(
                client,
                example_name,
                strategy,
                options.provider,
                options.model,
                options.seed,
                options.output,
                max_input_words=options.max_input_words,
                max_output_tokens=options.max_output_tokens,
                timeout_seconds=options.timeout_seconds,
                retries=options.retries,
            )
        )


def compare_runs(summary: Path, output: Path) -> Path:
    """Compare the completed runs of one saved example summary.

    Args:
        summary (Path): The completed example summary to read.
        output (Path): The directory for the comparison report.

    Returns:
        Path: The comparison report, with source run records and no new provider
            requests.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as folder:
        ...     summary = Path(folder) / "example-summary.json"
        ...     _ = summary.write_text('{"seed": 7, "methods": {}}')
        ...     comparison = compare_runs(summary, Path(folder) / "comparison")
        ...     comparison.name
        'comparison.json'
    """
    record = json.loads(summary.read_text())
    output.mkdir(parents=True, exist_ok=True)
    path = output / "comparison.json"
    path.write_text(
        json.dumps(
            {
                "source": str(summary.resolve()),
                "seed": record["seed"],
                "methods": record["methods"],
                "provider_requests_made": 0,
            },
            indent=2,
        )
        + "\n"
    )
    return path


def method_settings(
    strategy: str,
    provider: str,
    model: str,
    *,
    max_input_words: int = _MAX_INPUT_WORDS,
    max_output_tokens: int = _MAX_OUTPUT_TOKENS,
    timeout_seconds: float = _TIMEOUT_SECONDS,
    retries: int = 0,
) -> dict[str, object]:
    """Give the generation settings and request allocation of an example.

    Args:
        strategy (str): The selected decision procedure.
        provider (str): The hosted-provider identifier.
        model (str): The requested model identifier.
        max_input_words (int, optional): The maximum number of input words per
            request.
        max_output_tokens (int, optional): The maximum requested output tokens per
            response.
        timeout_seconds (float, optional): The timeout of one provider request in
            seconds.
        retries (int, optional): The maximum retries of a rate limit, timeout,
            transport failure or provider service failure per generated response.

    Returns:
        dict[str, object]: The generation settings and request allocations.

    Raises:
        ValueError: If the model, provider, strategy or a requested limit is
            invalid.

    Examples:
        >>> method_settings("coordinated", "openai", "selected-model")["period_calls"]
        6
        >>> method_settings("tools_memory", "google", "selected-model")["run_calls"]
        12
    """
    if not model.strip():
        raise ValueError("model must be selected explicitly")
    if strategy not in _STRATEGY_CALLS:
        raise ValueError(f"unsupported language-model strategy: {strategy}")
    if provider not in _PROVIDER_CLASSES:
        raise ValueError(f"unsupported provider: {provider}")
    if type(max_input_words) is not int or not 256 <= max_input_words <= 16384:
        raise ValueError("max_input_words: expected a value from 256 through 16384")
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096:
        raise ValueError("max_output_tokens: expected a value from 1 through 4096")
    if (
        isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 300
    ):
        raise ValueError("timeout_seconds: expected a value above 0 through 300")
    if type(retries) is not int or not 0 <= retries <= 2:
        raise ValueError("retries: expected an integer from 0 through 2")
    interaction_calls = _STRATEGY_CALLS[strategy]
    calls = interaction_calls * (retries + 1)
    period_seconds = math.ceil(timeout_seconds * calls)
    settings: dict[str, object] = {
        "provider": provider,
        "model": model,
        "max_input_words": max_input_words,
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "run_calls": calls * _HORIZON,
        "run_input_words": max_input_words * calls * _HORIZON,
        "run_output_tokens": max_output_tokens * calls * _HORIZON,
        "run_seconds": period_seconds * _HORIZON,
        "period_calls": calls,
        "period_input_words": max_input_words * calls,
        "period_output_tokens": max_output_tokens * calls,
        "period_seconds": period_seconds,
    }
    return settings
