from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
)


def breakdowns_of(periods: dict[str, Any]) -> list[tuple[int, Any]]:
    return [
        (period["period"], event)
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "breakdown"
    ]


def test_breakdowns_are_the_same_for_one_seed_whatever_the_decisions():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"] |= {
        "breakdown_chance": "0.5000",
        "breakdown_loss": {"min": "0.1000", "max": "0.3000"},
    }
    repair = {"kind": "repair", "line": "line-1", "amount": "0.0100"}
    found: list[list[tuple[int, Any]]] = []
    accepted: list[bool] = []
    for decisions in ({}, {2: [repair], 3: [repair]}):
        with api_client() as client:
            run = start_run(client, manifest, seed=21)
            run_to_the_end(client, run, decisions)
            _, periods = get(client, f"/runs/{run['id']}/periods")
        found.append(
            [(period, event["loss"]) for period, event in breakdowns_of(periods)]
        )
        accepted += [
            outcome["accepted"]
            for period in periods["periods"]
            for outcome in period["steps"][4]["outcomes"]
        ]

    assert accepted == [True, True]
    # Seed 21 breaks the line in periods 1, 3, 4 and 5 with these drawn losses.
    drawn = [
        (1, Decimal("0.1765")),
        (3, Decimal("0.2271")),
        (4, Decimal("0.1063")),
        (5, Decimal("0.2266")),
    ]
    assert found == [drawn, drawn]
