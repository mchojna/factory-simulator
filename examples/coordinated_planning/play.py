"""The cases of the example: their worlds, the play of a run and its audit.

Examples:
    >>> CASES["B3"]
    ('steady-market', 52)
"""

import contextlib
import json
from decimal import Decimal
from functools import partial
from pathlib import Path

import httpx2 as httpx

from examples import DEFAULT_SEED
from examples.coordinated_planning import EXAMPLE_NAME, STRATEGY
from examples.coordinated_planning.agent import CoordinatedAgent, settings_of
from examples.coordinated_planning.balances import violations_of_run
from examples.coordinated_planning.files import write_json
from examples.utils.cli import save_finished_run
from examples.utils.client import read_fixture
from examples.utils.providers import Provider, ProviderError
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject

# The scenario and horizon of each case: `small` is the scenario of the example
# fixtures, every other one a scenario of the library.
CASES = {
    "A3": ("small", 3),
    "B3": ("steady-market", 52),
    "C1": ("notice", 52),
    "C2": ("notice", 52),
}
# The checks of the audit of a finished run.
AUDIT_CHECKS = [
    "horizon",
    "profit terms",
    "ledger versus cash change",
    "customer unit balance",
    "supplier unit balance",
    "item balance",
    "rejected final decisions",
    "article equation 1",
]


def start_case(client: httpx.Client, case: str) -> tuple[JsonObject, int]:
    """Create the manifest and scenario of a case and start its run with seed 7.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        case (str): The case: A3, B3, C1 or C2.

    Returns:
        tuple[dict[str, Any], int]: The started run and its horizon.

    Raises:
        RuntimeError: If the HTTP interface refuses a request.

    Examples:
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"id": "r-1"}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> start_case(client, "A3")
        ({'id': 'r-1'}, 3)
    """
    scenario_name, horizon = CASES[case]
    return start_scenario(client, scenario_name), horizon


def start_scenario(client: httpx.Client, scenario_name: str) -> JsonObject:
    """Create the manifest and a scenario and start its run with seed 7.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        scenario_name (str): `small` for the scenario of the example fixtures, else
            the name of a scenario of the library.

    Returns:
        dict[str, Any]: The started run.

    Raises:
        RuntimeError: If the HTTP interface refuses a request.

    Examples:
        >>> transport = httpx.MockTransport(
        ...     lambda request: httpx.Response(200, text='{"id": "r-1"}')
        ... )
        >>> client = httpx.Client(transport=transport, base_url="http://server")
        >>> start_scenario(client, "notice")
        {'id': 'r-1'}
    """
    if scenario_name == "small":
        manifest = read_fixture("manifest.json")
        scenario = read_fixture("scenario.json")
    else:
        manifest = json.loads((EXAMPLES / "manifest.json").read_text())
        path = EXAMPLES / "scenarios" / f"{scenario_name}.json"
        scenario = json.loads(path.read_text())
    created = benchmark.send(client, "POST", "/manifests", manifest)
    scenario_id = benchmark.send(
        client, "POST", f"/manifests/{created['id']}/scenarios", scenario
    )["id"]
    return benchmark.start_run(client, str(scenario_id), DEFAULT_SEED)


def play_case(
    client: httpx.Client, case: str, provider: Provider, folder: Path
) -> JsonObject:
    """Play the run of a case with the coordinated agent and record every step.

    The decisions of a period are written to `pending-decisions.json` before they are
    sent, so a lost answer leaves them for inspection rather than a second submission.

    Args:
        client (httpx.Client): The client, its base URL the HTTP interface.
        case (str): The case: A3, B3, C1 or C2.
        provider (Provider): The provider of the model replies.
        folder (Path): The new directory of the run record.

    Returns:
        dict[str, Any]: The status of the run: its periods, provider calls and profit.

    Raises:
        FileExistsError: If the folder exists.
        ValueError: If model output or decisions are invalid.
        ProviderError: If a provider request fails.
        RuntimeError: If the HTTP interface, the budget or the audit fails.

    Examples:
        >>> with httpx.Client(base_url="http://server") as client:
        ...     play_case(client, "A3", None, Path("."))
        Traceback (most recent call last):
        ...
        FileExistsError: [Errno 17] File exists: '.'
    """
    folder.mkdir(parents=True, exist_ok=False)
    run, horizon = start_case(client, case)
    run_id = str(run["id"])
    settings = settings_of(horizon)
    write_json(folder / "start.json", run)
    write_json(folder / "settings.json", settings)
    agent = CoordinatedAgent(
        provider=provider,
        strategy=STRATEGY,
        settings=settings,
        check=partial(benchmark.create_check, client, run_id),
        folder=folder,
    )
    answer = run
    decisions: list[JsonObject] = []
    try:
        while not answer.get("finished", False):
            observation = benchmark.read(client, f"/runs/{run_id}/observation")
            write_json(folder / "last-observation.json", observation)
            entry = {
                "period": observation["period"],
                "decisions": agent(run["description"], observation),
            }
            write_json(folder / "pending-decisions.json", entry)
            answer = benchmark.send(client, "POST", f"/runs/{run_id}/decisions", entry)
            decisions.append(entry)
            write_json(folder / "decisions.json", decisions)
            closed = benchmark.read_periods(client, run_id)[-1]
            agent.record_event("closed-period", closed)
            agent.memory = [*agent.memory, _closed_summary(closed)][-2:]
            write_json(
                folder / "checkpoint.json",
                {"closed_periods": len(decisions), "provider_calls": agent.calls},
            )
        result = benchmark.read(client, f"/runs/{run_id}/result")
        periods = benchmark.read_periods(client, run_id)
        write_json(folder / "world.json", benchmark.read_world(client, run_id))
        write_json(folder / "audit.json", audit_of(run["description"], result, periods))
        write_json(folder / "periods.json", periods)
        write_json(folder / "result.json", result)
        save_finished_run(
            client, EXAMPLE_NAME, run, result, folder / "export", {"case": case}
        )
    except Exception as error:
        write_json(
            folder / "status.json",
            _failed_status(error, len(decisions), horizon, agent.calls),
        )
        # The periods the server closed stay readable after the answer is lost.
        with contextlib.suppress(Exception):
            write_json(
                folder / "partial-periods.json", benchmark.read_periods(client, run_id)
            )
        raise
    status: JsonObject = {
        "status": "complete",
        "completed_periods": len(decisions),
        "planned_periods": horizon,
        "provider_calls": agent.calls,
        "profit": result["profit"],
    }
    write_json(folder / "status.json", status)
    return status


def audit_of(
    description: JsonObject, result: JsonObject, periods: list[JsonObject]
) -> JsonObject:
    """Give the audit of a finished run: the balance checks and the profit equation.

    The profit equals the change of cash plus the receivables and the salvage.

    Args:
        description (dict[str, Any]): The description of the run.
        result (dict[str, Any]): The result of the run.
        periods (list[dict[str, Any]]): The closed periods of the run.

    Returns:
        dict[str, Any]: The checks, their violations, the receivables and the profit
            from the equation.

    Raises:
        RuntimeError: If a check fails.

    Examples:
        >>> from examples.coordinated_planning.balances import COST_KINDS
        >>> zero = Decimal(0)
        >>> state = {"customer_orders": [], "supplier_orders": [], "stock": {}}
        >>> close = {
        ...     "step": "close_period",
        ...     "measures": {"total": {"profit_so_far": zero}},
        ...     "state": {**state, "transfers": []},
        ... }
        >>> totals = ["units_ordered", "units_shipped", "units_lost"]
        >>> result = {
        ...     "periods": 1,
        ...     "profit": zero,
        ...     "terms": dict.fromkeys(
        ...         [*COST_KINDS, "revenue", "interest_earned", "salvage"], zero
        ...     ),
        ...     "cash_at_start": zero,
        ...     "cash_at_end": zero,
        ...     "measures": {
        ...         "total": {**dict.fromkeys(totals, zero), "decisions_rejected": 0},
        ...         "suppliers": {},
        ...         "customers": {"retail": {"receivables": zero}},
        ...     },
        ... }
        >>> description = {"scenario": {"horizon": 1, "start": {}}}
        >>> periods = [{"ledger": [], "steps": [close]}]
        >>> audit_of(description, result, periods)["violations"]
        []
    """
    violations = violations_of_run(STRATEGY, description, result, periods)
    receivables = sum(
        (
            Decimal(str(measures["receivables"]))
            for measures in result["measures"]["customers"].values()
        ),
        Decimal(0),
    )
    equation = (
        Decimal(str(result["cash_at_end"]))
        - Decimal(str(result["cash_at_start"]))
        + receivables
        + Decimal(str(result["terms"]["salvage"]))
    )
    if equation != Decimal(str(result["profit"])):
        violations.append(
            f"profit {result['profit']} is not the cash change plus receivables and "
            f"salvage {equation}"
        )
    if violations:
        raise RuntimeError(f"audit: {'; '.join(violations)}")
    return {
        "checks": AUDIT_CHECKS,
        "violations": violations,
        "receivables": receivables,
        "equation_1": equation,
    }


def _closed_summary(closed: JsonObject) -> JsonObject:
    """Give the memory of a closed period: its cash, stock and decision outcomes.

    Args:
        closed (dict[str, Any]): The closed period.

    Returns:
        dict[str, Any]: The period, the cash and stock at its close and the outcomes
            of its decisions.
    """
    state = closed["steps"][-1]["state"]
    return {
        "period": closed["period"],
        "cash": state["cash"],
        "stock": state["stock"],
        "outcomes": next(
            step["outcomes"]
            for step in closed["steps"]
            if step["step"] == "execute_decisions"
        ),
    }


def _failed_status(
    error: Exception, completed: int, horizon: int, calls: int
) -> JsonObject:
    """Give the status of a run that stopped, with the domain of its failure.

    Args:
        error (Exception): The failure.
        completed (int): The closed periods.
        horizon (int): The periods of the run.
        calls (int): The provider requests dispatched.

    Returns:
        dict[str, Any]: The status, the failure and its domain.
    """
    status: JsonObject = {
        "status": "incomplete",
        "completed_periods": completed,
        "planned_periods": horizon,
        "provider_calls": calls,
        "profit": None,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    if isinstance(error, ProviderError):
        status["failure_kind"] = error.kind
        status["failure_domain"] = "provider_or_transport"
    elif isinstance(error, ValueError):
        status["failure_domain"] = "model_output_or_input_validation"
    else:
        status["failure_domain"] = "infrastructure_or_budget"
    return status
