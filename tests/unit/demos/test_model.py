from typing import cast

import pytest

from demos.utils.model import method_settings


@pytest.mark.parametrize(
    ("strategy", "calls_per_period"),
    [("single_prompt", 2), ("tools_memory", 4), ("coordinated", 6)],
)
def test_demo_method_settings_bound_every_period_call_and_token(
    strategy: str, calls_per_period: int
):
    settings = method_settings(strategy, "openai", "selected-model")

    assert settings["period_calls"] == calls_per_period
    assert settings["run_calls"] == calls_per_period * 3
    assert (
        settings["period_tokens"]
        == (
            cast(int, settings["max_input_tokens"])
            + cast(int, settings["max_output_tokens"])
        )
        * calls_per_period
    )
    assert settings["run_tokens"] == cast(int, settings["period_tokens"]) * 3
    assert (
        settings["period_seconds"]
        == cast(float, settings["timeout_seconds"]) * calls_per_period
    )
    assert settings["run_seconds"] == cast(int, settings["period_seconds"]) * 3


@pytest.mark.parametrize("strategy", ["unknown", "mathematical"])
def test_demo_settings_refuse_a_strategy_without_a_language_model(strategy: str):
    with pytest.raises(ValueError, match="unsupported language-model strategy"):
        method_settings(strategy, "openai", "selected-model")


def test_transport_retries_reserve_their_full_call_token_and_time_budgets():
    settings = method_settings(
        "coordinated",
        "openai",
        "selected-model",
        max_input_tokens=2048,
        max_output_tokens=128,
        timeout_seconds=2.5,
        retries=2,
    )

    assert settings["period_calls"] == 18
    assert settings["run_calls"] == 54
    assert settings["period_tokens"] == 2176 * 18
    assert settings["run_tokens"] == 2176 * 54
    assert settings["period_seconds"] == 45
    assert settings["run_seconds"] == 135


def test_demo_settings_refuse_unbounded_live_request_settings():
    with pytest.raises(ValueError, match="max_input_tokens"):
        method_settings(
            "single_prompt", "openai", "selected-model", max_input_tokens=20000
        )
    with pytest.raises(ValueError, match="retries"):
        method_settings("single_prompt", "openai", "selected-model", retries=3)
