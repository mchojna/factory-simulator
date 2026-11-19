# The stubs of matplotlib leave the keyword arguments of its methods untyped.
# pyright: reportUnknownMemberType=false

import csv
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    localcontext,
)
from pathlib import Path
from textwrap import fill

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from scipy import stats

from stress.controls import HELD_EQUAL, INFORMATION_CONTROLS
from stress.playing import (
    AGENTS,
    COLUMNS,
    INFORMED_AGENTS,
    LIMITED_OPTIMIZERS,
    NAMED_MEASURES,
    PlayedRun,
    row_key_of,
    row_of,
)

SCORE_PLACES = Decimal("0.000000000001")
REPORT_PLACES = Decimal("0.001")
# The decimal context of a score and of its rounding. A profit of the record has at
# most 26 digits before the point and 12 after, so a score, the quotient of two
# differences of profits, has at most 39 digits before the point, and it is a half of
# the 12th place or lies at least 2.5e-51 from one. Its quotient to 100 digits lies
# within 1e-61 of the exact one, so it rounds to 12 places as the exact one does.
SCORE_CONTEXT = Context(
    prec=100, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero]
)
HARD_ENOUGH = Decimal("-0.03")
CALIBRATION_POLICY = "buffered_rolling_optimizer"
# The informed optimizer at the terminal value factor of the calibration policy.
INFORMED_POLICY = "buffered_informed_optimizer"
STEADY_MARKET = "steady-market"
COLORS = ("#1f6fb2", "#e3871c", "#3b9a4b", "#8e5cb0", "#c0392b")
CALIBRATION_RULE = (
    "The calibration reads one limited optimizer, fixed before the run: the buffered "
    "rolling optimizer. Its gap in a world is the profit of the reference less its "
    "profit. The calibration score of a world is 1 less that gap over the denominator "
    "of steady market in the same seed, the profit of the reference less that of no "
    "decisions there; in steady market it is the normalized score of the optimizer. A "
    "loss that the reference and the optimizer share leaves it unchanged, and so do "
    "the denominator of the scenario and the other limited optimizers. The difficulty "
    "pairs the calibration scores of each seed, so the differences of the seeds are "
    "independent, and the standard error and the 95 percent interval of the verdict "
    "cover their mean. The 95 percent interval of every comparison is the Student "
    "interval with the correction for skew of Hall (1992), and the Student interval "
    "itself when the differences have no skew. Each interval covers its own scenario: "
    "at a mean difference of -0.03, about 1 scenario in 20 still reads yes or no. A "
    "scenario whose reading holds foresight reads foresight and has no verdict: its "
    "gap holds what the reference knows of a disruption before a limited optimizer "
    "sees it. A scenario reads incomplete when a seed it plays has no calibration "
    "score in it or in steady market: a world has none when a solve of its reference "
    "has no solution, and a seed has none when its world of steady market is "
    "unscorable. The scores give the mean of each optimizer without an interval; the "
    "optimizer of the highest mean is chosen on the seeds of the report."
)
GAP_RULE = (
    "The largest gap of an optimizer is the most, in money, by which the solution of "
    "one of its integer solves can be below the bound of its program, over every "
    "solve with a solution in the scorable worlds: one that stopped at the gap limit "
    "of 0.01 units of money or at a limit of work. A gap bounds its program only. The "
    "later yes-or-no choices of a program take any value from 0 to 1, so the "
    "reference can earn less than the best policy by more than its gaps. A dash marks "
    "an optimizer without an integer solve with a solution in those worlds: its "
    "programs were linear, no solve found one, or no world is scorable."
)
UNSCORABLE_RULE = (
    "A world is unscorable when the reference makes no more profit than no decisions, "
    "or when a solve of the reference has no solution; it has no normalized score. "
    "The reference is a heuristic policy that never cancels a supplier order and "
    "runs the transfers of a period in the order of its routes, so a better decision "
    "can exist in an unscorable world. The table gives the profits of its runs."
)
INFORMATION_RULE = (
    "An information control of a scenario is the scenario without one information "
    "treatment, the same in every other key, played on the same manifest and seeds. "
    "The effect of the treatment is, per seed, the normalized score of the buffered "
    "rolling optimizer, fixed before the run, in the scenario less its normalized "
    "score in the control. The two worlds share no decisions and the reference, so "
    "the two scores share their denominator, and the standard error covers the mean "
    "of these differences, as in the calibration. A difference against steady market "
    "in the calibration compares scenarios that differ in more than one key, so it is "
    "no effect of information."
)
DISCLOSURE_RULE = (
    "The disclosure effect pairs two policies in the same world. The informed "
    "optimizer is the rolling optimizer that reads, before the run, the range of every "
    "hidden parameter group but disruptions.duration from a twin run with nothing "
    "hidden, and plans each range at its cut mean; it sees no value drawn for a "
    "period. The rolling optimizer learns hidden demand from the orders it sees and "
    "plans every other hidden group at its value without loss. The disclosure effect "
    "is, per seed, the score of the informed optimizer at the terminal value factor "
    "1.2 less that of the buffered rolling optimizer, the rolling optimizer at the "
    "same factor. It is the response of this heuristic policy to the disclosed "
    "ranges, and it can be negative. Both policies are fixed before the run, so the "
    "standard error covers the mean of the differences of the seeds. Every "
    "disclosure effect is a diagnostic; one of a single seed has no standard error "
    "and no bounds."
)
DECISION_VALUE_RULE = (
    "A normalized score divides by its denominator, the profit of the reference less "
    "that of no decisions, which differs from world to world, so a score can rise "
    "while the best limited profit falls and its gap to the reference grows. The best "
    "limited profit of a world is the highest profit of the five limited optimizers in "
    "it; its gap is the profit of the reference less it. The first table gives means "
    "over the worlds of each scenario; the second gives means of the differences "
    "against steady market over the seeds played in both, the score over the seeds "
    "scored in both. A lower score is no proof of a harder decision. The reading of a "
    "scenario names where its loss comes from: adaptation when a policy can avoid most "
    "of it, overload when most of it exceeds what the lines, suppliers or space allow, "
    "foresight when only a policy that knows a disruption before a limited optimizer "
    "sees it, as the reference does, can avoid it, recovery when credit binds first "
    "and a policy buys again, and information when the scenario changes what the "
    "optimizers know. Its evidence names what a policy can still do and the loss no "
    "policy avoids, worked at the middle of demand, prices and yields; a period of "
    "base demand is the middle demand of one period, 265 units."
)
# The reading of each scenario of the library and its evidence.
DECISION_VALUES = {
    "seasonal-demand": (
        "adaptation and overload",
        "Building products in periods 1 to 26 and moving them to the distribution "
        "centre serves part of the peak. The peak of periods 27 to 39 asks for 78 "
        "periods of base demand; the lines make about 15 of them in the peak and the "
        "spare hours and space before it hold about 19, so about 44 are lost by any "
        "policy.",
    ),
    "growth": (
        "overload",
        "From period 4 demand exceeds the most that the module assembly line allows, "
        "about 1.15 periods of base demand a period. Demand sums to about 233 periods "
        "of base demand against at most about 60 made, so about three quarters of it "
        "is lost by any policy; the choice left is which products the hours serve.",
    ),
    "decline": (
        "adaptation",
        "Buying and making less as demand falls keeps stock from ending at its salvage "
        "value. Demand sums to about 8.3 periods of base demand, about half of it by "
        "period 5, and from period 25 a period asks for less than 0.05 of base demand, "
        "so the second half of the run holds almost no decision.",
    ),
    "demand-surge": (
        "overload",
        "The surge asks for 760 smart monitors a period in periods 14 to 41. A display "
        "unit takes 0.3 hours of the module assembly line, so the line makes at most "
        "about 210 a period and no other component; at least about 15000 of the 21280 "
        "monitors of the surge are lost by any policy. The choice left is how the "
        "products share the hours of that line.",
    ),
    "demand-step": (
        "overload",
        "From period 11 demand is 6 times base demand, while the module assembly line "
        "allows about 1.15 times. About 202 of the 252 periods of base demand from "
        "period 11 are lost by any policy; the choice left is which products the hours "
        "serve.",
    ),
    "product-life-cycle": (
        "adaptation and overload",
        "The sensor gateway starts without stock of it or of its sensor module, and "
        "its demand ends in period 20, known from the start: launching in time and "
        "stopping before period 20 are the decisions. At its peak of 240 a period the "
        "spare hours of the module assembly and moulding lines add about 48 gateways "
        "to 80, so about 110 a period are lost unless other products give up their "
        "hours; an industrial controller earns more than a gateway for the same hours.",
    ),
    "supplier-outage": (
        "foresight and overload",
        "No microchip of either source arrives in periods 10 to 41, and every product "
        "needs one. A limited optimizer sees the outage in period 10 and loses every "
        "product for about 30 periods after its stock; the reference reads it before, "
        "and buying ahead is then bound by the credit limit, not by the suppliers or "
        "the space. The choice left after period 10 is which products the chips in "
        "stock serve.",
    ),
    "material-shortage": (
        "foresight and overload",
        "No microchip of either source can be bought in periods 10 to 41, and every "
        "product needs one; orders placed before still arrive. A limited optimizer "
        "sees the shortage in period 10 and loses every product for about 30 periods "
        "after its stock; the reference reads it before and can buy ahead within the "
        "credit limit.",
    ),
    "quality-crisis": (
        "foresight and overload",
        "Inspection accepts 0.001 of the PCB blanks and connector pins of their one "
        "supplier in periods 9 to 40, and every product needs a PCB blank. A limited "
        "optimizer sees the drop in period 9 and loses every product for about 29 "
        "periods after its stock. Blanks bought by period 6 arrive before it: the "
        "order limit of 2500 a period covers about 22 of the 32 periods, so at least "
        "about 10 are lost by any policy.",
    ),
    "transport-delays": (
        "foresight and overload",
        "Every delivery due in periods 12 to 41 arrives 16 periods late, so none "
        "arrives in periods 12 to 27. A policy that sees the delay in period 12 and "
        "keeps ordering loses every product for about 13 periods after its stock; "
        "buying ahead is bound by the space of the main plant, about 9 periods of "
        "materials, so at least about 4 periods are lost by any policy.",
    ),
    "line-breakdown": (
        "foresight and overload",
        "The final assembly line, the one line of every product, stops in period 18 "
        "and has no hours in periods 22 to 37. Its spare hours with overtime build "
        "about 0.3 periods of base demand a period ahead, about 5 of the 16 periods, "
        "so at least about 10 periods of every product are lost by any policy; a "
        "limited optimizer sees the cut in period 22.",
    ),
    "frequent-breakdowns": (
        "overload",
        "A breakdown takes 60 to 90 percent of the condition of the final assembly "
        "line in 8 of 10 periods, and a repair restores at most 0.7 a period. The line "
        "then has about half the hours its products need, so about half of demand is "
        "lost by any policy, and the cut of periods 34 to 41 stops it; repairing every "
        "period is the decision left.",
    ),
    "cash-squeeze": (
        "recovery",
        "Cash starts 40000 below minus the credit limit, so every buy is refused at "
        "first. Selling the stock brings cash back within the credit limit, and a buy "
        "of 500 microchips passes in period 7; demand beyond the stock is lost until "
        "the first buys arrive.",
    ),
    "full-warehouse": (
        "adaptation",
        "The main plant starts full, with no microchip, board or module in stock. "
        "Making 500 cable harnesses over two periods frees the space of a buy of 500 "
        "microchips; the first periods of every product are lost by any policy, since "
        "nothing they need is in stock and microchips take 2 periods or more to "
        "arrive.",
    ),
    "regional-crisis": (
        "foresight and overload",
        "No APAC delivery arrives in periods 16 to 41. Plastic resin, in every "
        "enclosure, comes from APAC only, so a limited optimizer that sees the crisis "
        "in period 16 loses every product for about 26 periods after its stock. Resin "
        "for the whole crisis costs about 8000 and takes about 7 units of space, so "
        "the reference, which reads the crisis before, can buy it ahead with about "
        "2100 microchips for the sensor modules; the alternative recipe and the second "
        "source of LCD panels cover the rest.",
    ),
    "surge-and-breakdown": (
        "overload",
        "The surge of smart monitors is that of demand-surge: at least about 15000 "
        "monitors are lost by any policy. The breakdown of the SMT line in period 16 "
        "costs about 1.5 periods of its hours, which a stock of 3 periods of "
        "components covers, so repairing it is the decision it adds.",
    ),
    "forecasts": (
        "information",
        "Its physical world is that of steady market, so no loss is forced. What "
        "hidden demand and its forecasts change for the limited optimizers is the "
        "effect of each treatment against its control.",
    ),
    "notice": (
        "information, foresight and overload",
        "The outage of supplier-outage, seen 4 periods before it starts. Acting on the "
        "notice buys about 3000 to 5000 microchips, 6 to 11 periods of need, before "
        "period 10, so a policy that sees only the notice still loses about 20 to 25 "
        "periods of every product. The reference reads the outage before the notice "
        "and earns what it earns in supplier-outage, buying ahead within the credit "
        "limit, so that loss is foresight beyond the notice. The effect of the notice "
        "is measured against supplier-outage.",
    ),
    "hidden-groups": (
        "information and overload",
        "Demand is 2.5 times base demand from period 1, while the module assembly line "
        "allows about 1.15 times, so about half of demand is lost by any policy, in "
        "the scenario and its visible twin alike. The effect of hiding is measured "
        "against that twin.",
    ),
    "capacity-cut": (
        "foresight and overload",
        "The SMT line, the one line of control boards and sensor modules, has no hours "
        "in periods 18 to 41. Its spare hours before build about 14 of the 24 periods "
        "of those components, so at least about 10 periods of every product are lost "
        "by any policy; a limited optimizer sees the cut in period 18.",
    ),
    "yield-drop": (
        "overload",
        "The SMT line keeps 0.05 of its yield in periods 7 to 40, so a good board "
        "takes 20 times the hours and materials. The line then makes about 0.13 "
        "periods of base demand of its components a period; with what periods 1 to 6 "
        "build ahead, at least about 20 of the 34 periods of every product are lost by "
        "any policy.",
    ),
    "price-change": (
        "adaptation and foresight",
        "A microchip bought in periods 8 to 39 costs 4 times its price, 26.00, and "
        "microchip-b keeps 7.70. A policy that sees the change in period 8 switches "
        "the control boards to microchip-b, about 2.50 a controller or monitor, and "
        "pays the change on the sensor gateway, about 20.30 a unit, which has no other "
        "recipe: at most about 66800 over the change. A policy that knows the change "
        "buys the chips of the gateways ahead; the supplier sells at most about 26 of "
        "the 32 periods of chips before period 8, so it switches the boards too and "
        "loses at most about 17600.",
    ),
}
NOT_ASSESSED = ("not assessed", "No assessment of this scenario.")
BUILT_CONTROLS = {control.control for control in INFORMATION_CONTROLS if control.built}

type RunKey = tuple[str, int, int, str]
# A scenario of a report: its name and its identifier.
type ScenarioKey = tuple[str, str]


# Where a stress report comes from: the package and the digest of its code, the solver
# environment of its runs, the digest of the checks of its runs, the digest of its
# analysis, the time and command, the manifest, the seeds, the line of the calibration
# protocol and the settings with the work limits of the program.
@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    version: str
    code: str
    solver_environment: str
    checks: str
    analysis: str
    time: str
    command: str
    manifest_name: str
    manifest_id: str
    seeds: range
    protocol: str
    settings: str


# The share of the gap from no decisions to the reference that a profit reaches, to 12
# places; None when the reference makes no more than no decisions.
def normalized_score(
    profit: Decimal, no_decisions_profit: Decimal, reference_profit: Decimal
) -> Decimal | None:
    with localcontext(SCORE_CONTEXT):
        gap = reference_profit - no_decisions_profit
        if gap <= 0:
            return None
        score = (profit - no_decisions_profit) / gap
        return score.quantize(SCORE_PLACES)


def key_of(run: PlayedRun) -> RunKey:
    return (run.scenario_id, run.seed, run.play, run.agent)


# The normalized score of every run against no decisions and the reference of the same
# play of its world; None for no decisions and in an unscorable world, one whose
# reference makes no more than no decisions or has a solve without a solution.
def scores_of(runs: list[PlayedRun]) -> dict[RunKey, Decimal | None]:
    profits = {key_of(run): run.profit for run in runs}
    without_solution = {
        (run.scenario_id, run.seed, run.play)
        for run in runs
        if run.agent == "reference" and run.solves_without_solution
    }
    scores: dict[RunKey, Decimal | None] = {}
    for run in runs:
        world = (run.scenario_id, run.seed, run.play)
        scores[key_of(run)] = None
        if run.agent != "no_decisions" and world not in without_solution:
            scores[key_of(run)] = normalized_score(
                run.profit,
                profits[(*world, "no_decisions")],
                profits[(*world, "reference")],
            )
    return scores


def rounded(value: Decimal) -> str:
    with localcontext(SCORE_CONTEXT):
        return str(value.quantize(REPORT_PLACES))


def program_of(runs: list[PlayedRun]) -> str:
    kinds = {"linear" if run.linear else "integer" for run in runs}
    return " and ".join(sorted(kinds)) or "-"


# The direction of the named measure of a scenario against `steady-market` with the
# same seed, for every agent of its row.
def direction_of(runs: list[PlayedRun], scenario: str) -> str:
    if scenario not in NAMED_MEASURES:
        return "not measured"
    path, direction, agents = NAMED_MEASURES[scenario]
    first_plays = [run for run in runs if run.play == 1 and run.agent in agents]
    steady = {
        (run.agent, run.seed): run.measures[path]
        for run in first_plays
        if run.scenario == STEADY_MARKET
    }
    compared = sorted(
        (
            run
            for run in first_plays
            if run.scenario == scenario and (run.agent, run.seed) in steady
        ),
        key=lambda run: (AGENTS.index(run.agent), run.seed),
    )
    if not compared:
        return "not measured"
    failures = [
        f"{run.agent} seed {run.seed}"
        for run in compared
        if not is_in_direction(
            run.measures[path], steady[run.agent, run.seed], direction
        )
    ]
    if failures:
        return "fails: " + ", ".join(failures)
    return "holds"


def is_in_direction(value: Decimal, steady: Decimal, direction: str) -> bool:
    if direction == "rises":
        return value > steady
    return value < steady


def provenance_lines(
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    provenance: Provenance,
) -> list[str]:
    worlds: dict[tuple[str, int], float] = {}
    for run in runs:
        world = (run.scenario_id, run.seed)
        worlds[world] = worlds.get(world, 0.0) + run.seconds
    references = [
        run for run in runs if run.agent == "reference" and scores[key_of(run)] is None
    ]
    without_solution = sum(1 for run in references if run.solves_without_solution)
    no_gain = len(references) - without_solution
    mean_seconds = "-"
    if worlds:
        mean_seconds = f"{statistics.mean(worlds.values()):.1f}"
    return [
        f"- Version: {provenance.version}",
        f"- Code: {provenance.code}",
        f"- Solver environment: {provenance.solver_environment}",
        f"- Checks: {provenance.checks}",
        f"- Analysis: {provenance.analysis}",
        f"- Time: {provenance.time}",
        f"- Command: {provenance.command}",
        f"- Manifest: {provenance.manifest_name}, {provenance.manifest_id}",
        f"- Seeds: {provenance.seeds[0]} to {provenance.seeds[-1]}",
        f"- Protocol: {provenance.protocol}",
        f"- Settings: {provenance.settings}",
        f"- Worlds: {len(worlds)} played, {len(references)} unscorable: {no_gain} "
        f"where the reference makes no more than no decisions, {without_solution} "
        "where a solve of the reference has no solution",
        f"- Mean seconds of a world: {mean_seconds}",
    ]


def scenario_key_of(run: PlayedRun) -> ScenarioKey:
    return (run.scenario, run.scenario_id)


def scenario_runs_of(runs: list[PlayedRun], scenario: ScenarioKey) -> list[PlayedRun]:
    return [run for run in runs if scenario_key_of(run) == scenario]


def scenario_lines(scenarios: list[ScenarioKey]) -> list[str]:
    lines = ["| Scenario | Identifier |", "| --- | --- |"]
    lines += [f"| {name} | {scenario_id} |" for name, scenario_id in scenarios]
    return lines


def score_lines(
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    scenarios: list[ScenarioKey],
) -> list[str]:
    lines = [
        "| Scenario | Optimizer | Program | Worlds scored | Mean | Lower quartile "
        "| Median | Upper quartile | Largest gap |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scenario in scenarios:
        scenario_runs = scenario_runs_of(runs, scenario)
        informed = [
            agent
            for agent in INFORMED_AGENTS
            if any(run.agent == agent for run in scenario_runs)
        ]
        for agent in ("reference", *LIMITED_OPTIMIZERS, *informed):
            scorable = [
                run
                for run in scenario_runs
                if run.agent == agent and scores[key_of(run)] is not None
            ]
            scored = scored_of(scorable, scores)
            values = ["-"] * 4
            if scored:
                quartiles = statistics.quantiles(scored, n=4, method="inclusive")
                values = [rounded(statistics.mean(scored))]
                values += [rounded(quartile) for quartile in quartiles]
            gaps = [run.largest_gap for run in scorable if run.largest_gap is not None]
            gap = f"{max(gaps):.4f}" if gaps else "-"
            cells = [scenario[0], agent, program_of(scorable), str(len(scored))]
            lines.append("| " + " | ".join([*cells, *values, gap]) + " |")
    return lines


def scored_of(
    runs: list[PlayedRun], scores: dict[RunKey, Decimal | None]
) -> list[Decimal]:
    return [score for run in runs if (score := scores[key_of(run)]) is not None]


# The highest score of the agents in each seed where one of them has a score.
def best_scores(
    runs: list[PlayedRun], scores: dict[RunKey, Decimal | None], agents: tuple[str, ...]
) -> dict[int, Decimal]:
    best: dict[int, Decimal] = {}
    for run in runs:
        score = scores[key_of(run)]
        if run.agent in agents and score is not None:
            best[run.seed] = max(score, best.get(run.seed, score))
    return best


# The scores of one side less those of another, per seed where both have one.
def paired_differences(
    first: dict[int, Decimal], second: dict[int, Decimal]
) -> list[Decimal]:
    return [first[seed] - second[seed] for seed in sorted(first.keys() & second.keys())]


def standard_error(values: list[Decimal]) -> Decimal:
    return statistics.stdev(values) / Decimal(len(values)).sqrt()


# The skew of the values: their third central moment over the second to the power
# 1.5, both moments over the count; 0 when the values are all equal.
def skew_of(values: list[Decimal]) -> Decimal:
    mean = statistics.mean(values)
    second = sum(((value - mean) ** 2 for value in values), Decimal(0)) / len(values)
    if second == 0:
        return Decimal(0)
    third = sum(((value - mean) ** 3 for value in values), Decimal(0)) / len(values)
    return third / second.sqrt() ** 3


def cube_root(value: Decimal) -> Decimal:
    root = abs(value) ** (Decimal(1) / 3)
    return root if value >= 0 else -root


# The 95 percent interval of the mean of at least 2 differences: the Student interval
# with the correction for skew of Hall (1992). Take n differences of mean m, standard
# deviation s and skew g, w = (m - true mean) / s, and t the 0.975 quantile of the
# Student t distribution with n - 1 degrees of freedom. The transform
# h(w) = w + g * w**2 / 3 + g**2 * w**3 / 27 lies within t / sqrt(n) of -g / (6 * n).
# Since h(w) = ((1 + g * w / 3)**3 - 1) / g, its inverse at y is
# 3 * y / (c**2 + c + 1), c the cube root of 1 + g * y, and each bound is m - s * w:
# the lower one at y = t / sqrt(n) - g / (6 * n), the upper one at
# y = -t / sqrt(n) - g / (6 * n). With g = 0 it is the Student interval. The verdict
# and the bounds of the report both read it. It sorts the differences first, so its
# rounded sums are the same in any order of the seeds.
def interval_of(differences: list[Decimal]) -> tuple[Decimal, Decimal]:
    ordered = sorted(differences)
    count = len(ordered)
    mean = statistics.mean(ordered)
    deviation = statistics.stdev(ordered)
    skew = skew_of(ordered)
    quantile = Decimal(str(stats.t.ppf(0.975, count - 1)))
    reach = quantile / Decimal(count).sqrt()
    shift = skew / (6 * count)

    def inverse(transformed: Decimal) -> Decimal:
        root = cube_root(1 + skew * transformed)
        return 3 * transformed / (root * root + root + 1)

    lower = mean - deviation * inverse(reach - shift)
    upper = mean - deviation * inverse(-reach - shift)
    return lower, upper


# Hard enough when the whole interval lies at most at -0.03; not hard enough when it
# lies at least at -0.03; undecided otherwise.
def hard_enough_of(differences: list[Decimal]) -> str:
    if len(differences) < 2:
        return "undecided"
    lower, upper = interval_of(differences)
    if upper <= HARD_ENOUGH:
        return "yes"
    if lower >= HARD_ENOUGH:
        return "no"
    return "undecided"


# The verdict of a scenario: foresight, with no verdict, when its reading holds
# foresight; incomplete when a seed it plays has no difference; else hard enough by
# the interval of the differences.
def verdict_of(scenario: str, differences: list[Decimal], seeds: int) -> str:
    if "foresight" in DECISION_VALUES.get(scenario, NOT_ASSESSED)[0]:
        return "foresight"
    if not differences or len(differences) < seeds:
        return "incomplete"
    return hard_enough_of(differences)


# The mean of the differences, their standard error and the bounds of their interval
# to 3 places; "-" without them, and the standard error and bounds "-" with fewer
# than 2.
def comparison_cells(differences: list[Decimal]) -> list[str]:
    if not differences:
        return ["-", "-", "-", "-"]
    mean = rounded(statistics.mean(differences))
    if len(differences) < 2:
        return [mean, "-", "-", "-"]
    lower, upper = interval_of(differences)
    return [mean, rounded(standard_error(differences)), rounded(lower), rounded(upper)]


# The calibration score of every world of the runs that has one, by scenario and seed:
# 1 less the gap of the calibration policy to the reference over the denominator of
# steady market in the same seed. A world without the run of the policy, whose
# reference has a solve without a solution, or whose seed has no scorable world of
# steady market, has none. In steady market it is the normalized score of the policy.
def calibration_scores(runs: list[PlayedRun]) -> dict[ScenarioKey, dict[int, Decimal]]:
    by_key = {key_of(run): run for run in runs}
    references = [
        run
        for run in runs
        if run.agent == "reference" and not run.solves_without_solution
    ]
    denominators: dict[int, Decimal] = {}
    for run in references:
        no_decisions = by_key.get((run.scenario_id, run.seed, run.play, "no_decisions"))
        if run.scenario == STEADY_MARKET and no_decisions is not None:
            denominator = run.profit - no_decisions.profit
            if denominator > 0:
                denominators[run.seed] = denominator
    worlds: dict[ScenarioKey, dict[int, Decimal]] = {}
    for run in references:
        policy = by_key.get((run.scenario_id, run.seed, run.play, CALIBRATION_POLICY))
        if policy is None or run.seed not in denominators:
            continue
        denominator = denominators[run.seed]
        with localcontext(SCORE_CONTEXT):
            gap = run.profit - policy.profit
            score = ((denominator - gap) / denominator).quantize(SCORE_PLACES)
        worlds.setdefault(scenario_key_of(run), {})[run.seed] = score
    return worlds


def calibration_lines(
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    scenarios: list[ScenarioKey],
) -> list[str]:
    lines = [
        "| Scenario | Worlds | Unscorable | Seeds compared | Calibration score "
        "| Against steady market | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound | Hard enough | Direction |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    steady_runs = [run for run in runs if run.scenario == STEADY_MARKET]
    calibration = calibration_scores(runs)
    steady = {
        seed: score
        for key, seeds in calibration.items()
        if key[0] == STEADY_MARKET
        for seed, score in seeds.items()
    }
    for scenario in scenarios:
        scenario_runs = scenario_runs_of(runs, scenario)
        references = [run for run in scenario_runs if run.agent == "reference"]
        unscorable = sum(1 for run in references if scores[key_of(run)] is None)
        own = calibration.get(scenario, {})
        cells = [scenario[0], str(len(references)), str(unscorable)]
        if scenario[0] == STEADY_MARKET:
            cells += [str(len(own)), mean_of(list(own.values()))]
            cells += ["-", "-", "-", "-", "-"]
        else:
            differences = paired_differences(own, steady)
            cells += [str(len(differences)), mean_of(list(own.values()))]
            cells += comparison_cells(differences)
            cells.append(verdict_of(scenario[0], differences, len(references)))
        cells.append(direction_of(scenario_runs + steady_runs, scenario[0]))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


# The effect of each information treatment whose scenario and control the runs hold:
# per seed, the score of the calibration policy in the scenario less that in its
# control.
def information_lines(
    runs: list[PlayedRun], scores: dict[RunKey, Decimal | None]
) -> list[str]:
    rows: list[str] = []
    for control in INFORMATION_CONTROLS:
        scenario_runs = [run for run in runs if run.scenario == control.scenario]
        control_runs = [run for run in runs if run.scenario == control.control]
        if not scenario_runs or not control_runs:
            continue
        differences = paired_differences(
            best_scores(scenario_runs, scores, (CALIBRATION_POLICY,)),
            best_scores(control_runs, scores, (CALIBRATION_POLICY,)),
        )
        cells = [
            control.scenario,
            control.treatment,
            control.control,
            ", ".join(sorted({run.scenario_id for run in control_runs})),
            HELD_EQUAL[control.treatment],
            str(len(differences)),
            *comparison_cells(differences),
        ]
        rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ["None."]
    return [
        "| Scenario | Treatment | Control | Control identifier | Held equal | Worlds "
        "| Effect of the treatment | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]


# The disclosure effect of each scenario with informed and rolling runs: per seed, the
# score of the informed optimizer at the factor 1.2 less that of the calibration
# policy.
def disclosure_lines(
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    scenarios: list[ScenarioKey],
) -> list[str]:
    rows: list[str] = []
    for scenario in scenarios:
        scenario_runs = scenario_runs_of(runs, scenario)
        informed = best_scores(scenario_runs, scores, (INFORMED_POLICY,))
        rolling = best_scores(scenario_runs, scores, (CALIBRATION_POLICY,))
        differences = paired_differences(informed, rolling)
        if not differences:
            continue
        cells = [
            scenario[0],
            "ranges of hidden groups disclosed",
            INFORMED_POLICY,
            CALIBRATION_POLICY,
            str(len(differences)),
            *comparison_cells(differences),
        ]
        rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ["None."]
    return [
        "| Scenario | Treatment | Informed run | Rolling run | Worlds "
        "| Disclosure effect | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]


# The runs of one world that its decision value reads: no decisions, the reference and
# the limited optimizer of the highest profit, the first of them in the order of
# `LIMITED_OPTIMIZERS` on a tie.
@dataclass(frozen=True, slots=True, kw_only=True)
class WorldOutcome:
    no_decisions: PlayedRun
    reference: PlayedRun
    best: PlayedRun

    @property
    def denominator(self) -> Decimal:
        return self.reference.profit - self.no_decisions.profit

    @property
    def gap(self) -> Decimal:
        return self.reference.profit - self.best.profit


# The outcome of every world of the runs, by scenario and seed; a world without a run
# of no decisions or of a limited optimizer has none.
def world_outcomes(
    runs: list[PlayedRun],
) -> dict[ScenarioKey, dict[int, WorldOutcome]]:
    by_key = {key_of(run): run for run in runs}
    worlds: dict[ScenarioKey, dict[int, WorldOutcome]] = {}
    for run in runs:
        if run.agent != "reference":
            continue
        world = (run.scenario_id, run.seed, run.play)
        limited = [
            by_key[(*world, agent)]
            for agent in LIMITED_OPTIMIZERS
            if (*world, agent) in by_key
        ]
        if not limited or (*world, "no_decisions") not in by_key:
            continue
        best = max(limited, key=lambda limited_run: limited_run.profit)
        worlds.setdefault(scenario_key_of(run), {})[run.seed] = WorldOutcome(
            no_decisions=by_key[(*world, "no_decisions")], reference=run, best=best
        )
    return worlds


# The units shipped over the units ordered of a run; None without an order.
def fill_rate(run: PlayedRun) -> Decimal | None:
    ordered = run.measures["units_ordered.total"]
    if ordered == 0:
        return None
    return run.measures["units_shipped.total"] / ordered


def mean_of(values: list[Decimal | None]) -> str:
    present = [value for value in values if value is not None]
    return rounded(statistics.mean(present)) if present else "-"


def absolute_cells(scenario: ScenarioKey, outcomes: list[WorldOutcome]) -> list[str]:
    references = [outcome.reference for outcome in outcomes]
    return [
        scenario[0],
        str(len(outcomes)),
        mean_of([outcome.no_decisions.profit for outcome in outcomes]),
        mean_of([run.profit for run in references]),
        mean_of([outcome.denominator for outcome in outcomes]),
        mean_of([outcome.best.profit for outcome in outcomes]),
        mean_of([outcome.gap for outcome in outcomes]),
        mean_of([fill_rate(run) for run in references]),
        mean_of([fill_rate(outcome.best) for outcome in outcomes]),
        *(
            mean_of([run.measures[path] for run in references])
            for path in (
                "units_lost.total",
                "units_ordered_from_suppliers.suppliers",
                "periods_below_credit_limit.total",
            )
        ),
    ]


# The absolute outcomes of each scenario, then their differences against steady market
# seed by seed, beside the reading of the scenario.
def decision_value_lines(
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    scenarios: list[ScenarioKey],
) -> list[str]:
    worlds = world_outcomes(runs)
    absolute = [
        "| Scenario | Worlds | No decisions | Reference | Denominator "
        "| Best limited profit | Gap to the reference | Fill rate of the reference "
        "| Fill rate of the best limited | Units lost by the reference "
        "| Units bought by the reference | Periods below the credit limit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    against = [
        "| Scenario | Worlds | Score against steady market "
        "| Profit against steady market | Gap against steady market "
        "| Denominator against steady market | Reading | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    steady_runs = [run for run in runs if run.scenario == STEADY_MARKET]
    steady = {
        seed: outcome
        for key, seeds in worlds.items()
        if key[0] == STEADY_MARKET
        for seed, outcome in seeds.items()
    }
    steady_scores = best_scores(steady_runs, scores, LIMITED_OPTIMIZERS)
    for scenario in scenarios:
        seeds = worlds.get(scenario, {})
        cells = absolute_cells(scenario, list(seeds.values()))
        absolute.append("| " + " | ".join(cells) + " |")
        if scenario[0] == STEADY_MARKET:
            continue
        paired = [
            (seeds[seed], steady[seed]) for seed in sorted(seeds.keys() & steady.keys())
        ]
        scenario_runs = scenario_runs_of(runs, scenario)
        score_differences = paired_differences(
            best_scores(scenario_runs, scores, LIMITED_OPTIMIZERS), steady_scores
        )
        reading, evidence = DECISION_VALUES.get(scenario[0], NOT_ASSESSED)
        cells = [
            scenario[0],
            str(len(paired)),
            mean_of(list(score_differences)),
            mean_of([world.best.profit - base.best.profit for world, base in paired]),
            mean_of([world.gap - base.gap for world, base in paired]),
            mean_of([world.denominator - base.denominator for world, base in paired]),
            reading,
            evidence,
        ]
        against.append("| " + " | ".join(cells) + " |")
    return [*absolute, "", *against]


# Every unscorable world of the first plays with its cause and the profits of no
# decisions, the reference and the limited optimizer that makes the most.
def unscorable_lines(
    runs: list[PlayedRun], scores: dict[RunKey, Decimal | None]
) -> list[str]:
    references = sorted(
        (
            run
            for run in runs
            if run.agent == "reference" and scores[key_of(run)] is None
        ),
        key=lambda run: (scenario_key_of(run), run.seed),
    )
    if not references:
        return ["None."]
    profits = {key_of(run): run.profit for run in runs}
    lines = [
        "| Scenario | Seed | Cause | No decisions | Reference | Best limited profit "
        "| Its optimizer |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for reference in references:
        world = (reference.scenario_id, reference.seed, reference.play)
        cause = "the reference makes no more than no decisions"
        if reference.solves_without_solution:
            cause = "a solve of the reference has no solution"
        limited = [
            (profits[(*world, agent)], agent)
            for agent in LIMITED_OPTIMIZERS
            if (*world, agent) in profits
        ]
        best = ["-", "-"]
        if limited:
            profit = max(profit for profit, _ in limited)
            agent = next(agent for value, agent in limited if value == profit)
            best = [str(profit), agent]
        cells = [
            reference.scenario,
            str(reference.seed),
            cause,
            str(profits[(*world, "no_decisions")]),
            str(reference.profit),
            *best,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def repeatable_lines(runs: list[PlayedRun], scenarios: list[ScenarioKey]) -> list[str]:
    lines = [
        "| Scenario | Runs with a solve at the time limit |",
        "| --- | --- |",
    ]
    for scenario in scenarios:
        count = sum(
            1 for run in scenario_runs_of(runs, scenario) if run.solves_at_time_limit
        )
        lines.append(f"| {scenario[0]} | {count} |")
    return lines


def without_solution_lines(
    runs: list[PlayedRun], scenarios: list[ScenarioKey]
) -> list[str]:
    rows: list[str] = []
    for scenario in scenarios:
        for agent in (*AGENTS[1:], *INFORMED_AGENTS):
            agent_runs = [
                run
                for run in scenario_runs_of(runs, scenario)
                if run.agent == agent and run.solves_without_solution
            ]
            if agent_runs:
                solves = sum(run.solves_without_solution for run in agent_runs)
                cells = [scenario[0], agent, str(len(agent_runs)), str(solves)]
                rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ["None."]
    return [
        "| Scenario | Optimizer | Runs | Solves without a solution |",
        "| --- | --- | --- | --- |",
        *rows,
    ]


# The violations the checks of the report found in its runs, then the violations of
# the worlds; a run of other checks holds no current violation.
def violation_lines(
    runs: list[PlayedRun], violations: list[str], checks: str
) -> list[str]:
    lines = [
        f"- {run.scenario} seed {run.seed} {run.agent} {run.run_id}: {message}"
        for run in runs
        if run.checks == checks
        for message in run.violations
    ]
    lines += [f"- {violation}" for violation in violations]
    return lines or ["None."]


# The score chart: a box of scores per limited optimizer in each scenario, two legend
# columns, wrapped optimizer names, scenario labels and title, a height that grows with
# the scenario count, and a PNG of the complete drawing with a margin.
def plot_scores(
    path: Path,
    runs: list[PlayedRun],
    scores: dict[RunKey, Decimal | None],
    scenarios: list[ScenarioKey],
    provenance: Provenance,
) -> None:
    figure = Figure(figsize=(8, 3 + 0.8 * len(scenarios)), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    for position, (agent, color) in enumerate(
        zip(LIMITED_OPTIMIZERS, COLORS, strict=True)
    ):
        boxes: list[list[float]] = []
        places: list[float] = []
        for row, scenario in enumerate(scenarios):
            agent_runs = [
                run for run in scenario_runs_of(runs, scenario) if run.agent == agent
            ]
            scored = scored_of(agent_runs, scores)
            if scored:
                boxes.append([float(score) for score in scored])
                places.append(row + (position - 2) * 0.16)
        if boxes:
            drawn = axes.boxplot(
                boxes,
                positions=places,
                widths=0.13,
                orientation="horizontal",
                patch_artist=True,
                medianprops={"color": "black"},
            )
            for box in drawn["boxes"]:
                box.set_facecolor(color)
    axes.set_yticks(range(len(scenarios)), [fill(name, 32) for name, _ in scenarios])
    axes.invert_yaxis()
    axes.set_xlabel("Normalized score")
    axes.set_title(
        fill(
            f"Normalized scores, {provenance.manifest_name}, seeds "
            f"{provenance.seeds[0]} to {provenance.seeds[-1]}",
            52,
        )
    )
    figure.legend(
        handles=[
            Patch(color=color, label=fill(agent, 30))
            for agent, color in zip(LIMITED_OPTIMIZERS, COLORS, strict=True)
        ],
        loc="outside lower center",
        ncols=2,
    )
    figure.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.1)


# The refusal of runs that hold more than one row of a key: each run of a world counts
# once.
def check_unique_rows(runs: list[PlayedRun]) -> None:
    counts = Counter(row_key_of(run) for run in runs)
    repeated = {
        row_key_of(run): f"{run.scenario} seed {run.seed} {run.agent} play {run.play}"
        for run in runs
        if counts[row_key_of(run)] > 1
    }
    if repeated:
        raise ValueError(
            f"the runs hold more than one row of {', '.join(repeated.values())}; "
            "take unique_runs first"
        )


# The refusal of runs of a solver environment other than the one of the report, naming
# each world of them once with its environment.
def check_solver_environment(runs: list[PlayedRun], solver_environment: str) -> None:
    others = {
        f"{run.scenario} seed {run.seed} under {run.solver_environment}": None
        for run in runs
        if run.solver_environment != solver_environment
    }
    if others:
        raise ValueError(
            "the runs hold rows of a solver environment other than "
            f"{solver_environment}: {', '.join(others)}"
        )


# The folder of a new report under the root, named by the time, with `report.md`,
# `runs.csv` and `scores.png`. Runs with more than one row of a key, or of a solver
# environment other than the one of the provenance, are refused.
def write_report(
    root: Path,
    runs: list[PlayedRun],
    violations: list[str],
    provenance: Provenance,
    now: datetime,
) -> Path:
    check_unique_rows(runs)
    check_solver_environment(runs, provenance.solver_environment)
    folder = root / f"{now:%Y-%m-%dT%H%M%S}-stress"
    folder.mkdir(parents=True, exist_ok=False)
    scores = scores_of(runs)
    first_plays = [run for run in runs if run.play == 1]
    scenarios = sorted({scenario_key_of(run) for run in runs})
    sections = [
        [f"# Stress test of {provenance.manifest_name}"],
        provenance_lines(first_plays, scores, provenance),
        ["## Scenarios"],
        scenario_lines(scenarios),
        ["## Scores"],
        [GAP_RULE],
        score_lines(first_plays, scores, scenarios),
        ["## Calibration"],
        [CALIBRATION_RULE],
        calibration_lines(
            first_plays,
            scores,
            [scenario for scenario in scenarios if scenario[0] not in BUILT_CONTROLS],
        ),
        ["## Decision value"],
        [DECISION_VALUE_RULE],
        decision_value_lines(
            first_plays,
            scores,
            [scenario for scenario in scenarios if scenario[0] not in BUILT_CONTROLS],
        ),
        ["## Information controls"],
        [INFORMATION_RULE],
        information_lines(first_plays, scores),
        ["## Disclosure effect"],
        [DISCLOSURE_RULE],
        disclosure_lines(first_plays, scores, scenarios),
        ["## Unscorable worlds"],
        [UNSCORABLE_RULE],
        unscorable_lines(first_plays, scores),
        ["## Not repeatable"],
        repeatable_lines(runs, scenarios),
        ["## Solves without a solution"],
        without_solution_lines(runs, scenarios),
        ["## Violations"],
        violation_lines(runs, violations, provenance.checks),
        ["![Normalized scores](scores.png)"],
    ]
    text = "\n\n".join("\n".join(lines) for lines in sections) + "\n"
    (folder / "report.md").write_text(text)
    with (folder / "runs.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=(*COLUMNS, "normalized_score"))
        writer.writeheader()
        for run in runs:
            score = scores[key_of(run)]
            writer.writerow(
                row_of(run) | {"normalized_score": "" if score is None else str(score)}
            )
    plot_scores(folder / "scores.png", first_plays, scores, scenarios, provenance)
    return folder
