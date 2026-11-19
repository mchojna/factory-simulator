import json
from pathlib import Path
from typing import cast

import httpx2 as httpx
import pytest
from pydantic import ValidationError

from examples.utils.model import ModelAgent, method_settings, model_example_parser
from examples.utils.providers import OpenAIProvider, ProviderError

PRODUCE = '{"kind": "produce", "line": "line-1", "item": "monitor", "quantity": 4}'


def reply(text: str = "[]", finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}, "finish_reason": finish_reason}]
        },
    )


def model_agent(
    folder: Path,
    answers: list[httpx.Response],
    sent: list[dict[str, object]],
    *,
    strategy: str = "single_prompt",
    retries: int = 0,
    max_input_words: int = 16384,
) -> ModelAgent:
    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return answers.pop(0)

    folder.mkdir(exist_ok=True)
    return ModelAgent(
        provider=OpenAIProvider(
            "selected-model",
            timeout_seconds=1,
            api_key="fixture-credential",  # pragma: allowlist secret
            transport=httpx.MockTransport(answer),
        ),
        strategy=strategy,
        settings={
            "max_input_words": max_input_words,
            "max_output_tokens": 16,
            "period_calls": 6,
            "retries": retries,
        },
        check=lambda period, decisions: [],
        folder=folder,
    )


def messages_of(request: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], request["messages"])


def events(folder: Path) -> list[dict[str, object]]:
    rows = (folder / "model-calls.jsonl").read_text().splitlines()
    return [json.loads(row) for row in rows]


@pytest.mark.parametrize(
    ("strategy", "calls_per_period"),
    [("single_prompt", 2), ("tools_memory", 4), ("coordinated", 6)],
)
def test_example_method_settings_bound_calls_input_words_and_output_tokens(
    strategy: str, calls_per_period: int
):
    settings = method_settings(strategy, "openai", "selected-model")

    assert settings["period_calls"] == calls_per_period
    assert settings["run_calls"] == calls_per_period * 3
    assert settings["period_input_words"] == 16384 * calls_per_period
    assert settings["period_output_tokens"] == 4096 * calls_per_period
    assert settings["run_input_words"] == cast(int, settings["period_input_words"]) * 3
    assert (
        settings["run_output_tokens"] == cast(int, settings["period_output_tokens"]) * 3
    )
    assert (
        settings["period_seconds"]
        == cast(float, settings["timeout_seconds"]) * calls_per_period
    )
    assert settings["run_seconds"] == cast(int, settings["period_seconds"]) * 3


@pytest.mark.parametrize("strategy", ["unknown", "mathematical"])
def test_example_settings_refuse_a_strategy_without_a_language_model(strategy: str):
    with pytest.raises(ValueError, match="unsupported language-model strategy"):
        method_settings(strategy, "openai", "selected-model")


def test_transport_retries_reserve_calls_words_output_tokens_and_time():
    settings = method_settings(
        "coordinated",
        "openai",
        "selected-model",
        max_input_words=2048,
        max_output_tokens=128,
        timeout_seconds=2.5,
        retries=2,
    )

    assert settings["period_calls"] == 18
    assert settings["run_calls"] == 54
    assert settings["period_input_words"] == 2048 * 18
    assert settings["run_input_words"] == 2048 * 54
    assert settings["period_output_tokens"] == 128 * 18
    assert settings["run_output_tokens"] == 128 * 54
    assert settings["period_seconds"] == 45
    assert settings["run_seconds"] == 135


def test_example_settings_refuse_unbounded_live_request_settings():
    with pytest.raises(ValueError, match="max_input_words"):
        method_settings(
            "single_prompt", "openai", "selected-model", max_input_words=20000
        )
    with pytest.raises(ValueError, match="retries"):
        method_settings("single_prompt", "openai", "selected-model", retries=3)


def test_example_settings_wait_120_seconds_and_accept_up_to_300():
    assert (
        method_settings("single_prompt", "openai", "selected-model")["timeout_seconds"]
        == 120
    )
    assert (
        method_settings(
            "single_prompt", "openai", "selected-model", timeout_seconds=300
        )["timeout_seconds"]
        == 300
    )
    with pytest.raises(ValueError, match="through 300"):
        method_settings(
            "single_prompt", "openai", "selected-model", timeout_seconds=301
        )


def test_the_word_limit_counts_every_message_before_dispatch(tmp_path: Path):
    sent: list[dict[str, object]] = []
    model_agent(tmp_path / "measured", [reply()], sent)({}, {"period": 1})
    words = sum(len(message["content"].split()) for message in messages_of(sent[0]))
    short = model_agent(tmp_path / "short", [reply()], sent, max_input_words=words - 1)
    exact = model_agent(tmp_path / "exact", [reply()], sent, max_input_words=words)

    with pytest.raises(ValueError, match="max_input_words"):
        short({}, {"period": 1})

    assert short.calls == 0
    assert not (tmp_path / "short" / "model-calls.jsonl").exists()
    assert exact({}, {"period": 1}) == []
    assert len(sent) == 2


def test_every_key_and_value_of_the_observation_is_a_word(tmp_path: Path):
    sent: list[dict[str, object]] = []
    observation = {"period": 1, "stock": {"board": "4", "chip": "10"}}

    model_agent(tmp_path, [reply()], sent)({}, observation)

    user = messages_of(sent[0])[1]["content"]
    assert user.split() == [
        '{"description":',
        "{},",
        '"observation":',
        '{"period":',
        "1,",
        '"stock":',
        '{"board":',
        '"4",',
        '"chip":',
        '"10"}}}',
    ]


@pytest.mark.parametrize("status", [429, 500, 503, 529])
def test_a_transient_failure_is_sent_again_within_the_retries(
    tmp_path: Path, status: int
):
    sent: list[dict[str, object]] = []
    agent = model_agent(
        tmp_path, [httpx.Response(status, json={}), reply()], sent, retries=1
    )

    assert agent({}, {"period": 1}) == []
    assert agent.calls == 2
    errors = [row for row in events(tmp_path) if row["kind"] == "provider-error"]
    assert [row["failure"] for row in errors] == [
        "rate_limit" if status == 429 else "service"
    ]


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (400, {}, "invalid_request"),
        (401, {}, "authentication"),
        (404, {}, "invalid_request"),
        (429, {"error": {"type": "insufficient_quota"}}, "authentication"),
    ],
)
def test_a_failure_that_is_not_transient_stops_without_another_request(
    tmp_path: Path, status: int, body: dict[str, object], kind: str
):
    sent: list[dict[str, object]] = []
    agent = model_agent(
        tmp_path, [httpx.Response(status, json=body), reply()], sent, retries=2
    )

    with pytest.raises(ProviderError) as failure:
        agent({}, {"period": 1})

    assert failure.value.kind == kind
    assert agent.calls == 1


def test_the_last_transient_failure_stops_the_agent(tmp_path: Path):
    sent: list[dict[str, object]] = []
    answers = [httpx.Response(429, json={}), httpx.Response(429, json={}), reply()]
    agent = model_agent(tmp_path, answers, sent, retries=1)

    with pytest.raises(ProviderError, match="rate_limit"):
        agent({}, {"period": 1})

    assert agent.calls == 2


@pytest.mark.parametrize(
    ("choice", "completion"),
    [
        ({"message": {"content": "[{"}, "finish_reason": "length"}, "truncated"),
        (
            {"message": {"content": None, "refusal": "No."}, "finish_reason": "stop"},
            "refused",
        ),
        ({"message": {"content": "[]"}}, "other"),
    ],
)
def test_an_incomplete_reply_stops_the_agent_and_stays_in_the_record(
    tmp_path: Path, choice: dict[str, object], completion: str
):
    sent: list[dict[str, object]] = []
    answers = [httpx.Response(200, json={"choices": [choice]}), reply()]
    agent = model_agent(tmp_path, answers, sent, retries=1)

    with pytest.raises(ValueError, match=f"model reply is {completion}"):
        agent({}, {"period": 1})

    assert agent.calls == 1
    replies = [row for row in events(tmp_path) if row["kind"] == "provider-response"]
    assert cast(dict[str, object], replies[0]["reply"])["completion"] == completion


def test_the_provider_and_model_come_from_the_command_then_the_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MODEL_PROVIDER", "google")
    monkeypatch.setenv("MODEL_NAME", "environment-model")
    parser = model_example_parser("planning")

    from_environment = parser.parse_args([])
    from_command = parser.parse_args(
        ["--provider", "anthropic", "--model", "command-model"]
    )

    assert (from_environment.provider, from_environment.model) == (
        "google",
        "environment-model",
    )
    assert (from_command.provider, from_command.model) == ("anthropic", "command-model")


@pytest.mark.parametrize("missing", ["--provider", "--model"])
def test_the_provider_and_model_are_required_without_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], missing: str
):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("MODEL_NAME", "")
    arguments = {"--provider": "openai", "--model": "selected-model"}
    del arguments[missing]

    with pytest.raises(SystemExit):
        model_example_parser("planning").parse_args(
            [part for pair in arguments.items() for part in pair]
        )

    assert missing in capsys.readouterr().err


@pytest.mark.parametrize(
    ("strategy", "answers"),
    [("single_prompt", 1), ("coordinated", 3)],
)
def test_an_array_strategy_asks_only_for_the_array_of_decisions(
    tmp_path: Path, strategy: str, answers: int
):
    sent: list[dict[str, object]] = []
    agent = model_agent(
        tmp_path, [reply() for _ in range(answers)], sent, strategy=strategy
    )

    assert agent({}, {"period": 1}) == []

    system = messages_of(sent[0])[0]["content"]
    assert system.endswith("Return only the JSON array of decisions.")
    assert '"kind":"final"' not in system


def test_the_tool_strategy_asks_only_for_objects_and_names_the_readable_fields(
    tmp_path: Path,
):
    sent: list[dict[str, object]] = []
    answers = [
        reply('{"kind": "read_current", "fields": ["cash"]}'),
        reply('{"kind":"final","decisions":[]}'),
    ]
    agent = model_agent(tmp_path, answers, sent, strategy="tools_memory")

    decisions = agent(
        {"items": [], "horizon": 3}, {"period": 1, "cash": "10.00", "stock": {}}
    )

    system = messages_of(sent[0])[0]["content"]
    assert decisions == []
    assert "JSON array of decisions." not in system
    assert "plain text holding one JSON object in one of four forms" in system
    assert "No functions are available." in system
    assert "Fields of the observation: cash, period, stock." in system
    assert "Fields of the description: horizon, items." in system
    result = json.loads(messages_of(sent[1])[-1]["content"])
    assert result == {"result": {"cash": "10.00"}}


def test_a_bare_array_from_the_tool_strategy_stops_the_agent(tmp_path: Path):
    sent: list[dict[str, object]] = []
    agent = model_agent(tmp_path, [reply()], sent, strategy="tools_memory")

    with pytest.raises(ValueError, match="tool response must be a JSON object"):
        agent({}, {"period": 1})

    assert len(sent) == 1


@pytest.mark.parametrize(
    "text",
    [
        '{"kind": "final"}',
        '{"kind": "final", "decisions": "none"}',
        '{"kind": "check_decisions"}',
        '{"kind": "check_decisions", "decisions": "none"}',
    ],
)
def test_a_tool_turn_without_a_decision_array_fails_the_decision_check(
    tmp_path: Path, text: str
):
    sent: list[dict[str, object]] = []
    agent = model_agent(tmp_path, [reply(text)], sent, strategy="tools_memory")

    with pytest.raises(ValidationError, match="valid list"):
        agent({}, {"period": 1})


@pytest.mark.parametrize(
    "text",
    [
        f"```json\n[{PRODUCE}]\n```",
        f"```\n[{PRODUCE}]\n```",
        f"\n```json\n[\n  {PRODUCE}\n]\n```\n",
        f"```json\r\n[{PRODUCE}]\r\n```\r\n",
    ],
)
def test_a_reply_that_is_one_code_block_is_read_from_inside_the_block(
    tmp_path: Path, text: str
):
    sent: list[dict[str, object]] = []

    decisions = model_agent(tmp_path, [reply(text)], sent)({}, {"period": 1})

    assert decisions == [json.loads(PRODUCE)]
    replies = [row for row in events(tmp_path) if row["kind"] == "provider-response"]
    assert cast(dict[str, object], replies[0]["reply"])["text"] == text


def test_the_tool_strategy_reads_a_turn_that_is_one_code_block(tmp_path: Path):
    sent: list[dict[str, object]] = []
    answers = [reply('```json\n{"kind": "final", "decisions": []}\n```')]
    agent = model_agent(tmp_path, answers, sent, strategy="tools_memory")

    assert agent({}, {"period": 1}) == []


@pytest.mark.parametrize(
    "text",
    [
        f"The plan:\n```json\n[{PRODUCE}]\n```",
        f'Stock is 4 (horizon 3).\n\n<invoke name="ship">\n</invoke>\n\n[{PRODUCE}]',
    ],
)
def test_the_json_value_at_the_end_of_a_reply_is_read(tmp_path: Path, text: str):
    sent: list[dict[str, object]] = []

    decisions = model_agent(tmp_path, [reply(text)], sent)({}, {"period": 1})

    assert decisions == [json.loads(PRODUCE)]


def test_a_reply_without_a_json_value_at_its_end_stops_the_agent(tmp_path: Path):
    sent: list[dict[str, object]] = []
    text = f"[{PRODUCE}]\nThat is the plan."

    with pytest.raises(ValueError, match="does not end with a JSON value"):
        model_agent(tmp_path, [reply(text)], sent)({}, {"period": 1})
