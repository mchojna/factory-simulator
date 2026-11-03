from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx2 as httpx

from factory_simulator.benchmark import client as benchmark
from factory_simulator.engine import build_economic_profile
from stress.playing import World, play_world
from stress.report import normalized_score, rounded

# The one treatment of an unscorable world in a scale study, fixed before any run.
SCALE_UNSCORABLE_RULE = (
    "A world is unscorable when the reference makes no more profit than no decisions, "
    "or when a solve of the reference has no solution. Every world of the protocol "
    "keeps its row with its economic profile and the profits of no decisions and the "
    "reference; an unscorable world has no score, counts in its pattern and stays "
    "out of the mean best score. No world is dropped or replaced."
)


# A scale study: patterns of counts, each generated with every generator seed in one
# economy, the scenario written for every manifest, the seeds of its runs and the
# agents played, no decisions and the reference first.
@dataclass(frozen=True, slots=True, kw_only=True)
class ScaleProtocol:
    patterns: dict[str, dict[str, int]]
    economy: str
    generator_seeds: range
    run_seeds: range
    scenario: dict[str, Any]
    agents: tuple[str, ...]


# One world of a scale study: its manifest by pattern and generator seed, the size of
# its graph, its economic profile, the profits of no decisions and the reference, the
# score of every other agent, None in an unscorable world, and the violations of its
# runs.
@dataclass(frozen=True, slots=True, kw_only=True)
class ScaleRow:
    pattern: str
    generator_seed: int
    seed: int
    manifest_id: str
    description: str
    items: int
    recipe_inputs: int
    catalogue_entries: int
    customer_products: int
    lines: int
    economic_class: str
    useful_demand_coverage: Decimal
    margin_share: Decimal
    no_decisions_profit: Decimal
    reference_profit: Decimal
    denominator: Decimal
    scores: dict[str, Decimal | None]
    violations: tuple[str, ...]


# The refusal of a scale study in another economy than the matched one, with fewer than
# two patterns, or whose agents do not start with no decisions and the reference.
def check_scale_protocol(protocol: ScaleProtocol) -> None:
    if protocol.economy != "matched":
        raise ValueError(
            f"a scale study plays the matched economy, not {protocol.economy}"
        )
    if len(protocol.patterns) < 2:
        raise ValueError("a scale study compares at least two patterns of counts")
    if protocol.agents[:2] != ("no_decisions", "reference"):
        raise ValueError("a scale study plays no decisions and the reference first")


# The row of the world of a pattern and a generator seed: its manifest generated over
# HTTP, the scenario of the protocol written for it and the agents played on one seed.
def play_scale_world(
    client: httpx.Client,
    protocol: ScaleProtocol,
    pattern: str,
    generator_seed: int,
    seed: int,
    time_limit: float,
) -> ScaleRow:
    body = {
        "counts": protocol.patterns[pattern],
        "seed": generator_seed,
        "economy": protocol.economy,
    }
    stored_manifest = benchmark.send(client, "POST", "/manifests/generated", body)
    path = f"/manifests/{stored_manifest['id']}/scenarios"
    scenario_id = benchmark.send(client, "POST", path, protocol.scenario)["id"]
    world = World(
        scenario=pattern,
        scenario_id=scenario_id,
        manifest_id=stored_manifest["id"],
        scenario_content=protocol.scenario,
        seed=seed,
        replay=False,
        agents=protocol.agents,
    )
    runs, failures = play_world(client, time_limit, "", "", world)
    if failures:
        raise RuntimeError(f"{pattern} seed {seed}: {failures[0]}")
    profits = {run.agent: run.profit for run in runs}
    reference = next(run for run in runs if run.agent == "reference")
    scorable = not reference.solves_without_solution
    scores = {
        agent: normalized_score(
            profits[agent], profits["no_decisions"], profits["reference"]
        )
        if scorable
        else None
        for agent in protocol.agents[2:]
    }
    content = stored_manifest["content"]
    profile = build_economic_profile(content)
    return ScaleRow(
        pattern=pattern,
        generator_seed=generator_seed,
        seed=seed,
        manifest_id=stored_manifest["id"],
        description=content["description"],
        items=sum(
            len(content[kind]) for kind in ("materials", "components", "products")
        ),
        recipe_inputs=sum(
            len(item["recipes"]["standard"])
            for kind in ("components", "products")
            for item in content[kind].values()
        ),
        catalogue_entries=sum(
            len(supplier["catalogue"]) for supplier in content["suppliers"].values()
        ),
        customer_products=len(profile.customer_products),
        lines=len(content["lines"]),
        economic_class=profile.economic_class,
        useful_demand_coverage=profile.useful_demand_coverage,
        margin_share=profile.margin_share,
        no_decisions_profit=profits["no_decisions"],
        reference_profit=profits["reference"],
        denominator=profits["reference"] - profits["no_decisions"],
        scores=scores,
        violations=tuple(violation for run in runs for violation in run.violations),
    )


# The rows of every world of a checked protocol: each pattern, generator seed and seed
# in order.
def play_scale_study(
    client: httpx.Client, protocol: ScaleProtocol, time_limit: float
) -> list[ScaleRow]:
    check_scale_protocol(protocol)
    return [
        play_scale_world(client, protocol, pattern, generator_seed, seed, time_limit)
        for pattern in protocol.patterns
        for generator_seed in protocol.generator_seeds
        for seed in protocol.run_seeds
    ]


def score_text(score: Decimal | None) -> str:
    return "-" if score is None else rounded(score)


# The best score of a world: the highest score of its agents after the reference, None
# in an unscorable world.
def best_score(row: ScaleRow) -> Decimal | None:
    scores = [score for score in row.scores.values() if score is not None]
    return max(scores, default=None)


# The rule of unscorable worlds, the table of every world and the table of every
# pattern with its worlds, its unscorable worlds and the mean best score of the others.
def scale_lines(rows: list[ScaleRow], agents: tuple[str, ...]) -> list[str]:
    scored = agents[2:]
    lines = [
        SCALE_UNSCORABLE_RULE,
        "",
        "| Pattern | Generator seed | Seed | Items | Recipe inputs | Catalogue entries "
        "| Customer products | Lines | Class | Coverage | Margin share | No decisions "
        "| Reference | Denominator | " + " | ".join(scored) + " |",
        "| --- " * (14 + len(scored)) + "|",
    ]
    for row in rows:
        cells = [
            row.pattern,
            str(row.generator_seed),
            str(row.seed),
            str(row.items),
            str(row.recipe_inputs),
            str(row.catalogue_entries),
            str(row.customer_products),
            str(row.lines),
            row.economic_class,
            str(row.useful_demand_coverage),
            str(row.margin_share),
            str(row.no_decisions_profit),
            str(row.reference_profit),
            format(row.denominator, "f"),
            *(score_text(row.scores[agent]) for agent in scored),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "| Pattern | Worlds | Unscorable | Mean best score |",
        "| --- | --- | --- | --- |",
    ]
    for pattern in dict.fromkeys(row.pattern for row in rows):
        best = [best_score(row) for row in rows if row.pattern == pattern]
        scores = [score for score in best if score is not None]
        mean = rounded(sum(scores, Decimal(0)) / len(scores)) if scores else "-"
        cells = [pattern, str(len(best)), str(len(best) - len(scores)), mean]
        lines.append("| " + " | ".join(cells) + " |")
    return lines
