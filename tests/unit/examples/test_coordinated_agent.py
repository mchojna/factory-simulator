import copy
from pathlib import Path
from typing import Any, cast

import pytest
from factories.coordinated import events_of, replying_provider

from examples.coordinated_planning import MODEL, STRATEGY
from examples.coordinated_planning.agent import (
    CoordinatedAgent,
    outcomes_by_position,
    settings_of,
)
from examples.coordinated_planning.play import CASES
from factory_simulator.benchmark.client import Check, JsonObject

REPAIR = {"kind": "repair", "line": "line-1", "amount": 1}


# A check that accepts the decisions at the accepted positions, keeping each checked
# list in checked when given.
def check_of(
    accepted: set[int], checked: list[list[JsonObject]] | None = None
) -> Check:
    def check(period: int, decisions: list[JsonObject]) -> list[JsonObject]:
        if checked is not None:
            checked.append(copy.deepcopy(decisions))
        return [
            {
                "decision_id": f"{period}-{position + 1}",
                "decision": decision,
                "accepted": position in accepted,
            }
            for position, decision in enumerate(decisions)
        ]

    return check


# A coordinated agent of three periods whose model gives the answers in order.
def coordinated_agent(
    folder: Path, answers: list[object], check: Check
) -> CoordinatedAgent:
    return CoordinatedAgent(
        provider=replying_provider(answers),
        strategy=STRATEGY,
        settings=settings_of(3),
        check=check,
        folder=folder,
    )


def test_the_settings_give_5_calls_a_period_and_795_calls_over_the_cases():
    calls = [settings_of(horizon)["run_calls"] for _, horizon in CASES.values()]

    assert sum(cast(list[int], calls)) == 795
    for _, horizon in CASES.values():
        settings = settings_of(horizon)
        assert settings["period_calls"] == 5
        assert settings["reasoning_effort"] == "low"
        assert settings["model"] == MODEL
        assert settings["run_output_tokens"] == 5 * horizon * 8192


def test_the_filter_maps_outcomes_in_execution_order_to_the_plan(tmp_path: Path):
    buy = {
        "kind": "buy",
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": 1,
        "warehouse": "main",
    }
    plan = [buy, REPAIR]

    def check(period: int, decisions: list[JsonObject]) -> list[JsonObject]:
        return [
            {
                "decision_id": f"{period}-{position + 1}",
                "decision": decision,
                "accepted": decision["kind"] == "repair",
            }
            for position, decision in reversed(list(enumerate(decisions)))
        ]

    agent = coordinated_agent(tmp_path, [[], [], plan, plan, plan], check)

    assert agent({"manifest": {}, "scenario": {}}, {"period": 1}) == [REPAIR]
    assert agent.calls == 5
    assert len(events_of(tmp_path)[-1]["filtered_decisions"]) == 1


def test_a_plan_the_filter_empties_is_checked_empty(tmp_path: Path):
    checked: list[list[JsonObject]] = []
    agent = coordinated_agent(
        tmp_path, [[], [], [REPAIR], [REPAIR], [REPAIR]], check_of(set(), checked)
    )

    assert agent({}, {"period": 1}) == []
    assert checked[-1] == []
    assert events_of(tmp_path)[-1]["filter_used"] is True


def test_the_filter_checks_again_until_no_decision_is_rejected(tmp_path: Path):
    plan = [REPAIR, {**REPAIR, "line": "line-2"}]
    checked: list[list[JsonObject]] = []
    # Each check rejects the first decision left, so 2 filter steps empty the plan.
    agent = coordinated_agent(
        tmp_path, [[], [], plan, plan, plan], check_of({1}, checked)
    )

    assert agent({}, {"period": 1}) == []
    assert agent.calls == 5
    steps = [event for event in events_of(tmp_path) if event["kind"] == "filter-step"]
    assert [len(step["after"]) for step in steps] == [1, 0]
    assert checked[-1] == []


@pytest.mark.parametrize("reply", ["not JSON", '[{"kind":"unknown"}]'])
def test_an_invalid_repair_stops_the_period_without_the_filter(
    tmp_path: Path, reply: str
):
    agent = coordinated_agent(tmp_path, [[], [], [REPAIR], reply], check_of(set()))

    with pytest.raises(ValueError, match=r"model reply|validation error"):
        agent({}, {"period": 1})

    assert agent.calls == 4
    assert all(event["kind"] != "filter-step" for event in events_of(tmp_path))


def test_a_failing_check_stops_the_period_before_the_filter(tmp_path: Path):
    def check(*_arguments: object) -> list[JsonObject]:
        raise RuntimeError("local HTTP interface unavailable")

    agent = coordinated_agent(tmp_path, [[], []], check)

    with pytest.raises(RuntimeError, match="unavailable"):
        agent({}, {"period": 1})

    assert agent.calls == 2
    assert all(event["kind"] != "filter-step" for event in events_of(tmp_path))


def test_a_rejected_earlier_production_stops_the_filter(tmp_path: Path):
    def check(*_arguments: object) -> list[JsonObject]:
        return [
            {"decision_id": "1-1", "decision": {"kind": "produce"}, "accepted": False}
        ]

    agent = coordinated_agent(tmp_path, [[], [], [], [], []], check)

    with pytest.raises(RuntimeError, match="earlier scheduled production"):
        agent({}, {"period": 2, "plans": [{"id": "make-1-1", "start": 2}]})

    assert agent.calls == 5
    assert all(event["kind"] != "filter-step" for event in events_of(tmp_path))


@pytest.mark.parametrize(
    "outcomes",
    [
        [{"accepted": True}],
        [{"accepted": True, "decision_id": "1-2", "decision": {"kind": "repair"}}],
        [{"accepted": "true", "decision_id": "1-1", "decision": {"kind": "repair"}}],
    ],
    ids=["no-identifier", "out-of-range", "accepted-as-text"],
)
def test_outcomes_that_do_not_name_each_decision_once_are_refused(
    outcomes: list[dict[str, Any]],
):
    with pytest.raises(RuntimeError, match="check"):
        outcomes_by_position(1, [{"kind": "repair"}], outcomes)
