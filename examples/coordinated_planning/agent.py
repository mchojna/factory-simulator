"""The coordinated agent: the reviewer repairs an infeasible plan, then a filter.

Examples:
    >>> settings_of(3)["period_calls"]
    5
"""

import copy
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import cast

from examples.coordinated_planning import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
    STRATEGY,
)
from examples.coordinated_planning.transport import TRANSPORT_POLICY, LiveProvider
from examples.utils.model import (
    ANSWERS,
    SYSTEM,
    ModelAgent,
    decisions_of,
    json_at_end,
    method_settings,
    payload_text,
)
from factory_simulator.benchmark.client import JsonObject

# The instruction of a repair request to the reviewer.
REPAIR_INSTRUCTION = (
    "Revise the entire plan using the validation results below. Every action "
    "in your final list must be feasible together, in its listed order, against "
    "the unchanged current observation. Preserve useful feasible actions where "
    "possible. Fix or omit actions rejected by the check. Do not assume that "
    "reducing quantity proportionally removes fixed setup or batch constraints. "
    "Respect the stated cash, credit, material, storage and line-capacity limits. "
    "Return only the complete JSON decision array."
)
# The repair requests of one period, after the planner, procurement and reviewer.
REVIEWER_REPAIRS = 2
_PERIOD_CALLS = 3 + REVIEWER_REPAIRS
# The error of the model agent when the check rejects the final plan.
_INFEASIBLE = "model proposed infeasible decisions; inspect model-calls.jsonl"


def settings_of(horizon: int) -> dict[str, object]:
    """Give the generation settings and request allocation of a run.

    Args:
        horizon (int): The periods of the run.

    Returns:
        dict[str, object]: The settings of the coordinated strategy with the fixed
            model, five calls a period and the transport policy.

    Examples:
        >>> settings = settings_of(52)
        >>> settings["run_calls"], settings["max_output_tokens"]
        (260, 8192)
    """
    settings = method_settings(STRATEGY, "openai", MODEL)
    max_input_words = cast(int, settings["max_input_words"])
    request_seconds = TRANSPORT_POLICY["logical_deadline"]
    settings.update(
        max_output_tokens=MAX_OUTPUT_TOKENS,
        reasoning_effort=REASONING_EFFORT,
        service_tier=SERVICE_TIER,
        nominal_calls=3 * horizon,
        max_reviewer_repairs=REVIEWER_REPAIRS,
        filter_policy="remove_rejected_and_recheck",
        transport_policy=TRANSPORT_POLICY,
        period_calls=_PERIOD_CALLS,
        period_input_words=_PERIOD_CALLS * max_input_words,
        period_output_tokens=_PERIOD_CALLS * MAX_OUTPUT_TOKENS,
        period_seconds=_PERIOD_CALLS * request_seconds,
    )
    for key in ("calls", "input_words", "output_tokens", "seconds"):
        settings[f"run_{key}"] = cast(int, settings[f"period_{key}"]) * horizon
    return settings


def outcomes_by_position(
    period: int,
    decisions: list[JsonObject],
    outcomes: object,
    scheduled_ids: Collection[str] = (),
) -> dict[int, JsonObject]:
    """Give the check outcome of every decision by its position in the plan.

    The check gives the outcomes in execution order. The identifier
    `<period>-<position>` of each outcome names its decision; the identifier of a
    production scheduled in an earlier period names no decision of the plan.

    Args:
        period (int): The period of the decisions.
        decisions (list[dict[str, Any]]): The checked decisions.
        outcomes (object): The outcomes the check gave.
        scheduled_ids (Collection[str], optional): The identifiers of the earlier
            productions that start in the period; none when not given.

    Returns:
        dict[int, dict[str, Any]]: The outcome of each decision, by its position from
            0.

    Raises:
        RuntimeError: If the outcomes do not name each decision once with its kind.

    Examples:
        >>> outcomes = [
        ...     {"decision_id": "1-2", "decision": {"kind": "ship"}, "accepted": True},
        ...     {"decision_id": "1-1", "decision": {"kind": "buy"}, "accepted": False},
        ... ]
        >>> positions = outcomes_by_position(
        ...     1, [{"kind": "buy"}, {"kind": "ship"}], outcomes
        ... )
        >>> positions[0]["accepted"]
        False
    """
    if not isinstance(outcomes, list):
        raise RuntimeError("check: outcomes are not a list")
    positions: dict[int, JsonObject] = {}
    seen: set[str] = set()
    for outcome in cast(list[JsonObject], outcomes):
        if type(outcome.get("accepted")) is not bool:
            raise RuntimeError("check: accepted is missing or not a boolean")
        identifier = outcome.get("decision_id", "")
        if identifier in seen:
            raise RuntimeError(f"check: {identifier} appears twice")
        seen.add(identifier)
        if identifier in scheduled_ids:
            if outcome.get("decision", {}).get("kind") != "produce":
                raise RuntimeError(f"check: {identifier} is not a production")
            continue
        parts = identifier.split("-")
        if len(parts) != 2 or parts[0] != str(period) or not parts[1].isdigit():
            raise RuntimeError(f"check: {identifier} names no decision of the plan")
        position = int(parts[1]) - 1
        if not 0 <= position < len(decisions) or position in positions:
            raise RuntimeError(f"check: {identifier} is out of range or repeated")
        if outcome.get("decision", {}).get("kind") != decisions[position]["kind"]:
            raise RuntimeError(f"check: {identifier} differs in kind from its decision")
        positions[position] = outcome
    if len(positions) != len(decisions):
        raise RuntimeError("check: outcomes do not cover every decision")
    return positions


@dataclass(slots=True, kw_only=True)
class CoordinatedAgent(ModelAgent):
    """The model agent whose reviewer repairs a plan the check rejects.

    The planner, procurement and reviewer roles make the plan of the model agent. When
    the check rejects it, the reviewer gets the plan and its outcomes up to two times.
    When the check still rejects the plan, the rejected decisions are removed and the
    rest is checked again, until the check accepts every decision left.

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
        last_check (dict[str, Any] | None, optional): The last checked decisions and
            their outcomes.
        scheduled_ids (set[str], optional): The identifiers of the earlier
            productions that start in the current period.

    Examples:
        >>> from pathlib import Path
        >>> from examples.coordinated_planning.transport import FixedOpenAIProvider
        >>> provider = FixedOpenAIProvider(
        ...     MODEL,
        ...     timeout_seconds=1,
        ...     api_key="example",  # pragma: allowlist secret
        ... )
        >>> agent = CoordinatedAgent(
        ...     provider=provider,
        ...     strategy=STRATEGY,
        ...     settings=settings_of(3),
        ...     check=lambda period, decisions: [],
        ...     folder=Path("."),
        ... )
        >>> agent.last_check is None
        True
    """

    last_check: JsonObject | None = None
    scheduled_ids: set[str] = field(default_factory=set[str])

    def record_event(self, kind: str, content: JsonObject) -> None:
        """Record an event, keeping the last check and the context of a live request.

        Args:
            kind (str): The event kind.
            content (dict[str, Any]): The observed event fields.

        Examples:
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from examples.coordinated_planning.transport import FixedOpenAIProvider
            >>> with TemporaryDirectory() as folder:
            ...     agent = CoordinatedAgent(
            ...         provider=FixedOpenAIProvider(
            ...             MODEL,
            ...             timeout_seconds=1,
            ...             api_key="example",  # pragma: allowlist secret
            ...         ),
            ...         strategy=STRATEGY,
            ...         settings=settings_of(3),
            ...         check=lambda period, decisions: [],
            ...         folder=Path(folder),
            ...     )
            ...     agent.record_event("decision-check", {"decisions": []})
            ...     agent.last_check
            {'decisions': []}
        """
        if kind == "provider-request" and isinstance(self.provider, LiveProvider):
            self.provider.set_context(content)
        if kind == "decision-check":
            self.last_check = copy.deepcopy(content)
        super().record_event(kind, content)

    def __call__(
        self, description: JsonObject, observation: JsonObject
    ) -> list[JsonObject]:
        """Choose, repair and filter the decisions of one period.

        Args:
            description (dict[str, Any]): The description of the run.
            observation (dict[str, Any]): The observation of the period.

        Returns:
            list[dict[str, Any]]: The decisions the check accepts, possibly none.

        Raises:
            ValueError: If input, model output or decisions violate their limits, or
                a reply is not complete.
            RuntimeError: If the check outcomes are inconsistent or the check rejects
                an earlier scheduled production.
            ProviderError: If the failure is not transient or the retries run out.

        Examples:
            >>> from pathlib import Path
            >>> from examples.coordinated_planning.transport import FixedOpenAIProvider
            >>> agent = CoordinatedAgent(
            ...     provider=FixedOpenAIProvider(
            ...         MODEL,
            ...         timeout_seconds=1,
            ...         api_key="example",  # pragma: allowlist secret
            ...     ),
            ...     strategy=STRATEGY,
            ...     settings={**settings_of(3), "max_input_words": 1},
            ...     check=lambda period, decisions: [],
            ...     folder=Path("."),
            ... )
            >>> agent({}, {"period": 1})
            Traceback (most recent call last):
            ...
            ValueError: model input exceeds max_input_words
        """
        period = int(observation["period"])
        self.last_check = None
        self.scheduled_ids = {
            plan["id"].removeprefix("make-")
            for plan in observation.get("plans", [])
            if plan["start"] == period
        }
        try:
            decisions = super().__call__(description, observation)
        except ValueError as error:
            if str(error) != _INFEASIBLE:
                raise
            if self.last_check is None:
                raise RuntimeError("check: the final plan has no outcomes") from error
        else:
            outcomes_by_position(
                period, decisions, self._last_check()["outcomes"], self.scheduled_ids
            )
            return self._finish(period, decisions, 0, None)
        decisions = self._last_check()["decisions"]
        outcomes = self._last_check()["outcomes"]
        outcomes_by_position(period, decisions, outcomes, self.scheduled_ids)
        common = {
            "description": description,
            "observation": observation,
            "closed_periods": self.memory,
        }
        for attempt in range(1, REVIEWER_REPAIRS + 1):
            context = {
                "role": "reviewer_repair",
                "attempt": attempt,
                "proposal": decisions,
                "checks": outcomes,
                "instruction": REPAIR_INSTRUCTION,
            }
            messages = [
                {"role": "system", "content": f"{SYSTEM} {ANSWERS[STRATEGY]}"},
                {"role": "user", "content": payload_text(common)},
                {"role": "user", "content": payload_text(context)},
            ]
            text = self._generate_text(messages, period)
            decisions = decisions_of(json_at_end(text))
            outcomes = self._checked(period, decisions, f"repair-{attempt}")
            if all(outcome["accepted"] for outcome in outcomes):
                return self._finish(period, decisions, attempt, None)
        return self._filtered(period, decisions, outcomes)

    def _filtered(
        self, period: int, decisions: list[JsonObject], outcomes: list[JsonObject]
    ) -> list[JsonObject]:
        """Remove the rejected decisions and check the rest until none is rejected.

        Args:
            period (int): The period of the decisions.
            decisions (list[dict[str, Any]]): The last plan of the reviewer.
            outcomes (list[dict[str, Any]]): The check outcomes of that plan.

        Returns:
            list[dict[str, Any]]: The decisions left, in their order in the plan.

        Raises:
            RuntimeError: If the check rejects an earlier scheduled production or the
                filter does not end.
        """
        planned = len(decisions)
        removed: list[JsonObject] = []
        for step in range(1, planned + 2):
            positions = outcomes_by_position(
                period, decisions, outcomes, self.scheduled_ids
            )
            if any(
                outcome["decision_id"] in self.scheduled_ids and not outcome["accepted"]
                for outcome in outcomes
            ):
                raise RuntimeError(
                    "check: an earlier scheduled production is rejected and the "
                    "filter keeps it"
                )
            rejected = {
                position
                for position, outcome in positions.items()
                if not outcome["accepted"]
            }
            if not rejected:
                return self._finish(
                    period, decisions, REVIEWER_REPAIRS, removed, planned
                )
            before = decisions
            dropped = [
                {"decision": decision, "outcome": positions[position]}
                for position, decision in enumerate(before)
                if position in rejected
            ]
            removed.extend(dropped)
            decisions = [
                decision
                for position, decision in enumerate(before)
                if position not in rejected
            ]
            if len(decisions) >= len(before):
                raise RuntimeError("filter: the plan did not get shorter")
            self.record_event(
                "filter-step",
                {
                    "period": period,
                    "iteration": step,
                    "before": before,
                    "removed": dropped,
                    "after": decisions,
                },
            )
            outcomes = self._checked(period, decisions, f"filter-{step}")
        raise RuntimeError("filter: checks ran past their limit")

    def _checked(
        self, period: int, decisions: list[JsonObject], phase: str
    ) -> list[JsonObject]:
        """Check decisions, confirm their outcomes and record them with their phase.

        Args:
            period (int): The period of the decisions.
            decisions (list[dict[str, Any]]): The decisions.
            phase (str): The repair or filter step of the check.

        Returns:
            list[dict[str, Any]]: The outcome of every decision, in execution order.
        """
        outcomes = self.check(period, decisions)
        outcomes_by_position(period, decisions, outcomes, self.scheduled_ids)
        self.record_event(
            "decision-check",
            {
                "period": period,
                "decisions": decisions,
                "outcomes": outcomes,
                "phase": phase,
            },
        )
        return outcomes

    def _last_check(self) -> JsonObject:
        """Give the last checked decisions and their outcomes.

        Returns:
            dict[str, Any]: The last decision-check event.

        Raises:
            RuntimeError: If no check is recorded in the period.
        """
        if self.last_check is None:
            raise RuntimeError("check: the final plan has no outcomes")
        return self.last_check

    def _finish(
        self,
        period: int,
        decisions: list[JsonObject],
        repairs: int,
        removed: list[JsonObject] | None,
        planned: int = 0,
    ) -> list[JsonObject]:
        """Record how the plan of the period was resolved and give its decisions.

        Args:
            period (int): The period of the decisions.
            decisions (list[dict[str, Any]]): The final decisions.
            repairs (int): The repair requests sent to the reviewer.
            removed (list[dict[str, Any]] | None): The decisions the filter removed
                with their outcomes; None when the filter did not run.
            planned (int, optional): The decisions of the plan the filter got; 0 when
                not given.

        Returns:
            list[dict[str, Any]]: The final decisions.
        """
        self.record_event(
            "period-resolution",
            {
                "period": period,
                "repairs": repairs,
                "filter_used": removed is not None,
                "filter_input_count": planned,
                "filtered_decisions": removed or [],
                "final_decision_count": len(decisions),
                "empty_final_plan": not decisions,
                "provider_calls_this_period": self.period_calls,
                "final_decisions": decisions,
            },
        )
        return decisions
