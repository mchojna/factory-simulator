import csv
import math
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import cast
from unittest.mock import patch

import numpy
import pytest
from factories import example_count
from hypothesis import given, settings
from hypothesis import strategies as st
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from factory_simulator.api.services.examples import EXAMPLES
from stress import report
from stress.playing import AGENTS, MEASURE_PATHS, PlayedRun, unique_runs
from stress.report import (
    DECISION_VALUE_RULE,
    DECISION_VALUES,
    DISCLOSURE_RULE,
    INFORMATION_RULE,
    LIMITED_OPTIMIZERS,
    UNSCORABLE_RULE,
    Provenance,
    best_scores,
    calibration_lines,
    comparison_cells,
    direction_of,
    disclosure_lines,
    hard_enough_of,
    information_lines,
    interval_of,
    normalized_score,
    scores_of,
    world_outcomes,
    write_report,
)
from stress.test_playing import SOLVER_ENVIRONMENT, hand_run

profit_values = st.decimals(min_value=-(10**9), max_value=10**9, places=2)
PROVENANCE = Provenance(
    version="0.4.0",
    code="c0de",
    solver_environment=SOLVER_ENVIRONMENT,
    checks="c4ec5",
    analysis="a7a1",
    time="2026-10-12T10:00:00",
    command="tests/stress -m stress",
    manifest_name="Electronics factory with economies of scale",
    manifest_id="m1",
    seeds=range(5),
    protocol="development; development seeds 0 to 999, evaluation seeds 1000 to 1019",
    settings="time_limit=60.0, node_limit=1000, gap_limit=0.01",
)
OPTIMIZER_PROFITS = {
    "full_horizon_optimizer": (100, 300, 500, 700),
    "rolling_optimizer": (800, 800, 800, 800),
    "aligned_optimizer": (-100, -100, -100, -100),
    "myopic_optimizer": (0, 0, 0, 0),
    "buffered_rolling_optimizer": (0, 0, 0, 0),
}


# Steady market on seeds 0 to 3, no decisions at -100 and the reference at 900, and
# seed 4, where the reference makes -300 against -100.
def hand_runs() -> list[PlayedRun]:
    runs: list[PlayedRun] = []
    for seed in range(5):
        runs.append(hand_run("no_decisions", seed, profit=Decimal(-100)))
        reference_profit = -300 if seed == 4 else 900
        runs.append(
            hand_run("reference", seed, profit=Decimal(reference_profit), linear=False)
        )
        for agent, profits in OPTIMIZER_PROFITS.items():
            profit = profits[seed] if seed < 4 else 0
            runs.append(hand_run(agent, seed, profit=Decimal(profit), linear=False))
    return [
        replace(run, largest_gap=0.0085)
        if (run.agent, run.seed) == ("full_horizon_optimizer", 1)
        else run
        for run in runs
    ]


def report_of(
    runs: list[PlayedRun], folder: Path, now: datetime = datetime(2026, 10, 12, 10)
) -> str:
    return (write_report(folder, runs, [], PROVENANCE, now) / "report.md").read_text()


# A row of an agent in a scenario, with its named measure.
def measured_row(agent: str, scenario: str, seed: int, units_lost: int) -> PlayedRun:
    measures = dict.fromkeys(MEASURE_PATHS, Decimal(0))
    measures["units_lost.total"] = Decimal(units_lost)
    return replace(hand_run(agent, seed), scenario=scenario, measures=measures)


def rolling_row(scenario: str, seed: int, units_lost: int) -> PlayedRun:
    return measured_row("rolling_optimizer", scenario, seed, units_lost)


# No decisions -100 and the reference 900; the rolling optimizer scores 0 in seed 0,
# played twice, and 1 in seed 1. A stop wrote the rolling run of seed 0 once more.
def resumed_runs() -> list[PlayedRun]:
    rolling = {0: -100, 1: 900}
    runs = [
        hand_run(
            agent,
            seed,
            play=play,
            run_id=f"{agent}-{seed}-{play}",
            profit=Decimal({"no_decisions": -100, "reference": 900}.get(agent, 0)),
        )
        for seed, plays in ((0, (1, 2)), (1, (1,)))
        for play in plays
        for agent in AGENTS
    ]
    runs = [
        replace(run, profit=Decimal(rolling[run.seed]))
        if run.agent == "rolling_optimizer"
        else run
        for run in runs
    ]
    first_rolling = next(run for run in runs if run.agent == "rolling_optimizer")
    return [replace(first_rolling, run_id="rolling_optimizer-0-stopped"), *runs]


# No decisions -100 and the reference 900 in every world, so a score is
# (profit + 100) / 1000, and every limited optimizer but the rolling and buffered
# rolling ones at 0, which make the same. In seed 2 of steady market the rolling
# optimizer makes 850, above the 840 of the buffered rolling optimizer.
def calibration_runs() -> list[PlayedRun]:
    rolling = {
        "steady-market": (850, 860, 840),
        "scenario-a": (790, 790, 760),
        "scenario-b": (850, 850, 850),
        "scenario-c": (800, 820, 780),
    }
    informed = {"informed_optimizer": (800, 790, 770)}
    informed["buffered_informed_optimizer"] = (810, 800, 780)
    runs: list[PlayedRun] = []
    for scenario, profits in rolling.items():
        for seed in range(3):
            agents = {"no_decisions": -100, "reference": 900}
            agents |= dict.fromkeys(OPTIMIZER_PROFITS, 0)
            agents["rolling_optimizer"] = profits[seed]
            agents["buffered_rolling_optimizer"] = profits[seed]
            if (scenario, seed) == ("steady-market", 2):
                agents["rolling_optimizer"] = 850
            if scenario == "scenario-a":
                agents |= {agent: values[seed] for agent, values in informed.items()}
            runs += [
                hand_run(
                    agent,
                    seed,
                    scenario=scenario,
                    scenario_id=scenario,
                    profit=Decimal(profit),
                    linear=False,
                )
                for agent, profit in agents.items()
            ]
    return runs


difference_lists = st.lists(
    st.decimals(min_value=Decimal("-0.2"), max_value=Decimal("0.1"), places=3),
    min_size=2,
    max_size=20,
)
score_differences = st.decimals(
    min_value=Decimal("-0.2"), max_value=Decimal("0.1"), places=12
)


# No decisions -100 and the reference 900 in every seed, so a score is
# (profit + 100) / 1000; one seed per profit of each agent.
def crossing_runs(profits: dict[str, tuple[int, ...]]) -> list[PlayedRun]:
    seeds = len(next(iter(profits.values())))
    agents = {"no_decisions": (-100,) * seeds, "reference": (900,) * seeds}
    agents |= dict.fromkeys(OPTIMIZER_PROFITS, (0,) * seeds) | profits
    return [
        hand_run(agent, seed, profit=Decimal(values[seed]), linear=False)
        for agent, values in agents.items()
        for seed in range(seeds)
    ]


# Profits of the informed optimizer at the factors 1.01 and 1.2, then of the rolling
# and the buffered rolling optimizers, per seed, from 2 to 6 seeds.
factor_profits = st.lists(
    st.lists(st.integers(-100, 900), min_size=4, max_size=4), min_size=2, max_size=6
)
DISCLOSURE_AGENTS = (
    "informed_optimizer",
    "buffered_informed_optimizer",
    "rolling_optimizer",
    "buffered_rolling_optimizer",
)


def disclosure_of(profits: list[list[int]]) -> list[str]:
    runs = crossing_runs(
        {
            agent: tuple(seed[position] for seed in profits)
            for position, agent in enumerate(DISCLOSURE_AGENTS)
        }
    )
    return disclosure_lines(runs, scores_of(runs), [("steady-market", "s1")])


# Profits of the five limited optimizers in steady market and in one scenario, per
# seed, from 2 to 6 seeds.
seed_profits = st.lists(
    st.tuples(
        st.lists(st.integers(-100, 900), min_size=5, max_size=5),
        st.lists(st.integers(-100, 900), min_size=5, max_size=5),
    ),
    min_size=2,
    max_size=6,
)


def limited_runs(profits: list[tuple[list[int], list[int]]]) -> list[PlayedRun]:
    runs: list[PlayedRun] = []
    for seed, sides in enumerate(profits):
        for scenario, side in zip(("steady-market", "scenario-a"), sides, strict=True):
            agents = {"no_decisions": -100, "reference": 900}
            agents |= dict(zip(LIMITED_OPTIMIZERS, side, strict=True))
            runs += [
                hand_run(
                    agent,
                    seed,
                    scenario=scenario,
                    scenario_id=scenario,
                    profit=Decimal(profit),
                )
                for agent, profit in agents.items()
            ]
    return runs


def calibration_of(runs: list[PlayedRun]) -> list[str]:
    scenarios = [("scenario-a", "scenario-a"), ("steady-market", "steady-market")]
    return calibration_lines(runs, scores_of(runs), scenarios)


# The cells of the verdict of the scenario: the seeds compared, its calibration score,
# the difference, its standard error, its bounds and hard enough.
def verdict_cells(runs: list[PlayedRun]) -> list[str]:
    return calibration_of(runs)[2].split(" | ")[3:10]


# The worlds of seed_profits with the scenario world of each seed losing an amount in
# its reference and its five limited optimizers, and, when shared, in no decisions too.
def losing_runs(
    profits: list[tuple[list[int], list[int]]], losses: list[int], shared: bool
) -> list[PlayedRun]:
    losers = {"reference", *LIMITED_OPTIMIZERS}
    if shared:
        losers.add("no_decisions")
    return [
        replace(run, profit=run.profit - losses[run.seed])
        if run.scenario == "scenario-a" and run.agent in losers
        else run
        for run in limited_runs(profits)
    ]


SPREAD = 0.03
CAMPAIGNS = 4000
# Three Monte Carlo standard errors of the share of 95 and of 2.5 percent.
COVERAGE_TOLERANCE = 3 * math.sqrt(0.95 * 0.05 / CAMPAIGNS)
SIDE_TOLERANCE = 3 * math.sqrt(0.025 * 0.975 / CAMPAIGNS)
type Differences = numpy.ndarray[tuple[int, int], numpy.dtype[numpy.float64]]


# The share of each verdict over the campaigns of differences, one row a campaign.
def verdict_shares(differences: Differences) -> dict[str, float]:
    verdicts = Counter(
        hard_enough_of([Decimal(f"{value:.12f}") for value in campaign])
        for campaign in differences.tolist()
    )
    return {
        verdict: verdicts[verdict] / CAMPAIGNS for verdict in ("yes", "no", "undecided")
    }


# The shares of the verdicts in an independent run of the interval as Hall (1992)
# states it, in floats with numpy, over 2000000 campaigns of 20 skewed differences.
SKEWED_SHARES = {"yes": 0.01739, "no": 0.04269, "undecided": 0.93992}


# One world of a scenario: no decisions, the reference and the five limited optimizers,
# the buffered rolling optimizer at its profit and every other one at the profits
# given, 0 when not given.
def policy_world(
    scenario: str,
    seed: int,
    no_decisions: int,
    reference: int,
    policy: int,
    **others: int,
) -> list[PlayedRun]:
    agents = {"no_decisions": no_decisions, "reference": reference}
    agents |= dict.fromkeys(LIMITED_OPTIMIZERS, 0) | others
    agents["buffered_rolling_optimizer"] = policy
    return [
        hand_run(
            agent,
            seed,
            scenario=scenario,
            scenario_id=scenario,
            profit=Decimal(profit),
        )
        for agent, profit in agents.items()
    ]


def calibration_rows(runs: list[PlayedRun]) -> list[str]:
    scenarios = sorted({(run.scenario, run.scenario_id) for run in runs})
    return calibration_lines(runs, scores_of(runs), scenarios)[2:]


# No decisions -100 and the reference 900, so a score is (profit + 100) / 1000. Five
# optimizers apart: in seed k each one scores a value of 0.84, 0.855, 0.87, 0.885 and
# 0.90, in an order that gives every optimizer each value once over seeds 0 to 4, a
# mean of 0.87 and a best of 0.90 in every world.
APART = (740, 755, 770, 785, 800)


def apart_world(scenario: str, seed: int) -> list[PlayedRun]:
    profits = APART[seed:] + APART[:seed]
    others = dict(zip(LIMITED_OPTIMIZERS, profits, strict=True))
    policy = others.pop("buffered_rolling_optimizer")
    return policy_world(scenario, seed, -100, 900, policy, **others)


def tied_world(scenario: str, seed: int, profit: int) -> list[PlayedRun]:
    others = dict.fromkeys(LIMITED_OPTIMIZERS[:-1], profit)
    return policy_world(scenario, seed, -100, 900, profit, **others)


# The worlds of seed_profits as hidden-groups, the scenario side, and its visible twin,
# the steady market side.
def information_of(profits: list[tuple[list[int], list[int]]]) -> list[str]:
    names = {"steady-market": "hidden-groups-shown", "scenario-a": "hidden-groups"}
    runs = [
        replace(run, scenario=names[run.scenario], scenario_id=names[run.scenario])
        for run in limited_runs(profits)
    ]
    return information_lines(runs, scores_of(runs))


# One world of a scenario: no decisions, the reference, the rolling optimizer at the
# profit given and every other limited optimizer at 0.
def world_runs(
    scenario: str, seed: int, no_decisions: int, reference: int, limited: int
) -> list[PlayedRun]:
    agents = {"no_decisions": no_decisions, "reference": reference}
    agents |= dict.fromkeys(LIMITED_OPTIMIZERS, 0)
    agents["rolling_optimizer"] = limited
    return [
        hand_run(
            agent,
            seed,
            scenario=scenario,
            scenario_id=scenario,
            profit=Decimal(profit),
        )
        for agent, profit in agents.items()
    ]


def decision_value_of(report: str) -> list[str]:
    return report.split("## Decision value\n\n")[1].split("\n\n## ")[0].split("\n\n")


# A run of steady market with its profit and the outcomes of its result.
def outcome_run(
    agent: str, seed: int, profit: int, shipped: int, **outcomes: int
) -> PlayedRun:
    measures = dict.fromkeys(MEASURE_PATHS, Decimal(0))
    measures["units_ordered.total"] = Decimal(100)
    measures["units_shipped.total"] = Decimal(shipped)
    for path, value in {
        "units_lost.total": outcomes.get("lost", 0),
        "units_ordered_from_suppliers.suppliers": outcomes.get("bought", 0),
        "periods_below_credit_limit.total": outcomes.get("below", 0),
    }.items():
        measures[path] = Decimal(value)
    return hand_run(agent, seed, profit=Decimal(profit), measures=measures)


def test_a_profit_scores_its_share_of_the_gap_between_no_decisions_and_the_reference():
    score = normalized_score(Decimal(300), Decimal(-100), Decimal(900))

    assert score == Decimal("0.4")


def test_the_reference_scores_1_and_no_decisions_scores_0():
    assert normalized_score(Decimal(900), Decimal(-100), Decimal(900)) == 1
    assert normalized_score(Decimal(-100), Decimal(-100), Decimal(900)) == 0


def test_a_reference_equal_to_no_decisions_gives_no_score():
    assert normalized_score(Decimal(5), Decimal(7), Decimal(7)) is None


def test_half_the_gap_from_no_decisions_to_the_reference_scores_one_half():
    score = normalized_score(Decimal(400), Decimal(-100), Decimal(900))

    assert str(score) == "0.500000000000"


def test_a_reference_below_no_decisions_gives_no_score():
    assert normalized_score(Decimal(-50), Decimal(-100), Decimal(-300)) is None
    assert normalized_score(Decimal(-50), Decimal(-100), Decimal(-100)) is None


def test_a_profit_of_1e13_over_a_gap_of_0_0001_scores_1e17():
    score = normalized_score(Decimal("1e13"), Decimal(0), Decimal("0.0001"))

    assert score == Decimal(10**17)
    assert str(score) == "100000000000000000.000000000000"


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(profit_values, profit_values, profit_values)
def test_a_profit_between_no_decisions_and_the_reference_scores_from_0_to_1(
    first: Decimal, second: Decimal, third: Decimal
):
    no_decisions, profit, reference = sorted([first, second, third])

    score = normalized_score(profit, no_decisions, reference)

    if no_decisions < reference:
        assert score is not None
        assert 0 <= score <= 1
    else:
        assert score is None


# Steady market in seed 0: no decisions makes 0, the reference 0.0001 and every limited
# optimizer 1e13, so each scores 1e13 / 0.0001 = 1e17.
def test_the_report_writes_a_score_of_1e17(tmp_path: Path):
    runs = [
        hand_run("no_decisions", profit=Decimal(0)),
        hand_run("reference", profit=Decimal("0.0001"), linear=False),
        *(
            hand_run(agent, profit=Decimal("1e13"), linear=False)
            for agent in LIMITED_OPTIMIZERS
        ),
    ]

    folder = write_report(tmp_path, runs, [], PROVENANCE, datetime(2026, 10, 12, 10))
    lines = (folder / "report.md").read_text().splitlines()
    with (folder / "runs.csv").open(newline="") as file:
        scores = {row["agent"]: row["normalized_score"] for row in csv.DictReader(file)}

    assert scores["rolling_optimizer"] == "100000000000000000.000000000000"
    assert (
        "| steady-market | rolling_optimizer | integer | 1 | 100000000000000000.000 "
        "| 100000000000000000.000 | 100000000000000000.000 | 100000000000000000.000 "
        "| - |"
    ) in lines


def test_the_report_gives_the_scores_and_the_verdict_of_hand_rows(tmp_path: Path):
    report = report_of(hand_runs(), tmp_path)

    lines = report.splitlines()
    assert lines[0] == "# Stress test of Electronics factory with economies of scale"
    assert lines[2:7] == [
        "- Version: 0.4.0",
        "- Code: c0de",
        "- Solver environment: scipy=1.18.1, highs=1.12.0",
        "- Checks: c4ec5",
        "- Analysis: a7a1",
    ]
    assert lines[10:12] == [
        "- Seeds: 0 to 4",
        "- Protocol: development; development seeds 0 to 999, evaluation seeds 1000 "
        "to 1019",
    ]
    assert (
        "| steady-market | full_horizon_optimizer | integer | 4 | 0.500 | 0.350 "
        "| 0.500 | 0.650 | 0.0085 |"
    ) in lines
    assert (
        "| steady-market | rolling_optimizer | integer | 4 | 0.900 | 0.900 | 0.900 "
        "| 0.900 | - |"
    ) in lines
    # (0 - -100) / (900 - -100) = 0.1 in each of the 4 scorable seeds.
    assert (
        "| steady-market | myopic_optimizer | integer | 4 | 0.100 | 0.100 | 0.100 "
        "| 0.100 | - |"
    ) in lines
    assert (
        "| steady-market | reference | integer | 4 | 1.000 | 1.000 | 1.000 | 1.000 "
        "| - |"
    ) in lines
    # The buffered rolling optimizer makes 0 in seeds 0 to 3, a calibration score of
    # 0.1; seed 4 of steady market is unscorable, so it has none.
    assert (
        "| steady-market | 5 | 1 | 4 | 0.100 | - | - | - | - | - | not measured |"
    ) in lines


# Seed 4 is unscorable: the reference makes -300 against -100. There alone the
# full-horizon optimizer has linear programs and a largest gap of 0.5.
def test_the_program_and_the_largest_gap_of_the_scores_read_the_scorable_worlds_only(
    tmp_path: Path,
):
    runs = [
        replace(run, linear=True, largest_gap=0.5)
        if (run.agent, run.seed) == ("full_horizon_optimizer", 4)
        else run
        for run in hand_runs()
    ]

    lines = report_of(runs, tmp_path).splitlines()

    assert (
        "| steady-market | full_horizon_optimizer | integer | 4 | 0.500 | 0.350 "
        "| 0.500 | 0.650 | 0.0085 |"
    ) in lines


def test_the_report_names_the_solver_environment_of_every_run_and_refuses_another(
    tmp_path: Path,
):
    other = "scipy=1.19.0, highs=1.13.0"
    mixed = [
        replace(run, solver_environment=other) if run.seed == 4 else run
        for run in hand_runs()
    ]
    report = write_report(
        tmp_path, hand_runs(), [], PROVENANCE, datetime(2026, 10, 12, 10)
    )
    with (report / "runs.csv").open(newline="") as file:
        environments = {row["solver_environment"] for row in csv.DictReader(file)}
    lines = (report / "report.md").read_text().splitlines()
    with pytest.raises(ValueError) as refused:
        report_of(mixed, tmp_path, datetime(2026, 10, 12, 11))

    assert "- Solver environment: scipy=1.18.1, highs=1.12.0" in lines
    assert environments == {SOLVER_ENVIRONMENT}
    assert str(refused.value) == (
        "the runs hold rows of a solver environment other than "
        "scipy=1.18.1, highs=1.12.0: steady-market seed 4 under "
        "scipy=1.19.0, highs=1.13.0"
    )


def test_the_report_lists_the_runs_with_a_solve_without_a_solution(tmp_path: Path):
    runs = [
        replace(run, solves_without_solution=1)
        if (run.agent, run.seed) == ("full_horizon_optimizer", 2)
        else run
        for run in hand_runs()
    ]
    runs.append(
        replace(
            next(
                run
                for run in hand_runs()
                if run.agent == "rolling_optimizer" and run.seed == 2
            ),
            agent="informed_optimizer",
            solves_without_solution=1,
        )
    )
    report = report_of(runs, tmp_path)
    without = report_of(hand_runs(), tmp_path, datetime(2026, 10, 12, 11))

    section = report.split("## Solves without a solution\n\n")[1].split("\n\n")[0]
    assert "| steady-market | full_horizon_optimizer | 1 | 1 |" in section.splitlines()
    assert "| steady-market | informed_optimizer | 1 | 1 |" in section.splitlines()
    assert len(section.splitlines()) == 4
    assert "## Solves without a solution\n\nNone.\n" in without


def test_runs_csv_holds_every_row_with_its_normalized_score(tmp_path: Path):
    runs = hand_runs()
    folder = write_report(tmp_path, runs, [], PROVENANCE, datetime(2026, 10, 12, 10))
    with (folder / "runs.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))

    scores = {(row["agent"], row["seed"]): row["normalized_score"] for row in rows}
    assert len(rows) == len(runs)
    assert scores["full_horizon_optimizer", "0"] == "0.200000000000"
    assert [score for (_, seed), score in scores.items() if seed == "4"] == [""] * 7


def test_the_report_lists_the_violations_of_its_checks_only(tmp_path: Path):
    runs = [
        replace(run, violations=("decisions rejected: 1",), checks="a")
        if run.agent == "rolling_optimizer" and run.seed == 0
        else replace(run, violations=("ended after period 2 of 3",))
        if run.agent == "aligned_optimizer" and run.seed == 1
        else run
        for run in hand_runs()
    ]
    report = report_of(runs, tmp_path)

    section = report.split("## Violations\n\n")[1].split("\n\n")[0]
    assert section == (
        "- steady-market seed 1 aligned_optimizer aligned_optimizer-1: ended after "
        "period 2 of 3"
    )


def test_each_report_gets_a_new_folder_with_its_chart(tmp_path: Path):
    root = tmp_path
    first = write_report(
        root, hand_runs(), [], PROVENANCE, datetime(2026, 10, 12, 10, 0, 0)
    )
    write_report(root, hand_runs(), [], PROVENANCE, datetime(2026, 10, 12, 10, 0, 1))
    folders = sorted(path.name for path in root.iterdir())
    with pytest.raises(FileExistsError):
        write_report(
            root, hand_runs(), [], PROVENANCE, datetime(2026, 10, 12, 10, 0, 0)
        )
    chart = (first / "scores.png").read_bytes()

    assert folders == ["2026-10-12T100000-stress", "2026-10-12T100001-stress"]
    assert chart.startswith(b"\x89PNG")


def test_the_direction_holds_when_the_measure_moves_its_way_in_every_seed():
    steady = [rolling_row("steady-market", seed, 10) for seed in (0, 1)]
    falling = [
        rolling_row("demand-surge", 0, 15),
        rolling_row("demand-surge", 1, 10),
    ]
    rising = [
        rolling_row("demand-surge", 0, 15),
        rolling_row("demand-surge", 1, 12),
    ]

    assert (
        direction_of(steady + falling, "demand-surge")
        == "fails: rolling_optimizer seed 1"
    )
    assert direction_of(steady + rising, "demand-surge") == "holds"


def test_units_lost_are_measured_without_the_reference_that_loses_none():
    steady = [
        measured_row("reference", "steady-market", 0, 0),
        rolling_row("steady-market", 0, 730),
    ]
    surge = [
        measured_row("reference", "demand-surge", 0, 0),
        rolling_row("demand-surge", 0, 1934),
    ]

    assert direction_of(steady + surge, "demand-surge") == "holds"


def test_the_direction_of_an_information_scenario_reads_only_its_agent():
    steady = [
        measured_row("reference", "steady-market", 0, 10),
        measured_row("rolling_optimizer", "steady-market", 0, 10),
    ]
    reference = measured_row("reference", "forecasts", 0, 10)
    falling = measured_row("rolling_optimizer", "forecasts", 0, 8)
    level = measured_row("rolling_optimizer", "forecasts", 0, 10)

    assert direction_of([*steady, reference, falling], "forecasts") == "holds"
    assert (
        direction_of([*steady, reference, level], "forecasts")
        == "fails: rolling_optimizer seed 0"
    )


def test_two_versions_of_a_scenario_are_reported_apart_by_their_identifiers(
    tmp_path: Path,
):
    runs = [
        replace(run, scenario="capacity-cut", scenario_id=scenario_id)
        for scenario_id in ("c1", "c2")
        for run in hand_runs()
    ]
    report = report_of(runs, tmp_path)

    scores = report.split("## Scores\n\n")[1].split("\n\n")[1].splitlines()
    scenarios = report.split("## Scenarios\n\n")[1].split("\n\n")[0].splitlines()
    rolling = [line for line in scores if "| rolling_optimizer |" in line]
    assert (
        rolling
        == [
            "| capacity-cut | rolling_optimizer | integer | 4 | 0.900 | 0.900 | 0.900 "
            "| 0.900 | - |"
        ]
        * 2
    )
    assert scenarios == [
        "| Scenario | Identifier |",
        "| --- | --- |",
        "| capacity-cut | c1 |",
        "| capacity-cut | c2 |",
    ]


def test_a_run_written_twice_by_a_stop_counts_once_in_the_scores(tmp_path: Path):
    runs, violations = unique_runs(resumed_runs())
    report = report_of(runs, tmp_path)
    with pytest.raises(ValueError) as refused:
        report_of(resumed_runs(), tmp_path, datetime(2026, 10, 12, 11))

    # Scores 0 and 1: mean 0.5, inclusive quartiles 0.25, 0.5 and 0.75. Counted twice,
    # seed 0 would read 3 worlds and a mean of 0.333.
    assert violations == []
    assert (
        "| steady-market | rolling_optimizer | integer | 2 | 0.500 | 0.250 | 0.500 "
        "| 0.750 | - |"
    ) in report.splitlines()
    assert str(refused.value) == (
        "the runs hold more than one row of steady-market seed 0 rolling_optimizer "
        "play 1; take unique_runs first"
    )


# The calibration scores of the buffered rolling optimizer in steady market are 0.95,
# 0.96 and 0.94, mean 0.95; the 0.95 of the rolling optimizer in seed 2 leaves them.
# Each comparison below has a standard deviation of 0.01, no skew, a standard error of
# 0.01 / sqrt(3) = 0.005774 and, with t(2) = 4.302653, a half-width of 0.024843.
# Against steady market: a -0.06, -0.07, -0.08: mean -0.070, from -0.095 to -0.045,
# yes. b 0, -0.01, 0.01: mean 0, from -0.025 to 0.025, no. c -0.05, -0.04, -0.06:
# mean -0.050, from -0.075 to -0.025, undecided.
# The disclosure effect of a: the informed run at 1.2 0.91, 0.90, 0.88 less the
# buffered rolling optimizer 0.89, 0.89, 0.86, so 0.02, 0.01, 0.02, mean 0.017,
# standard error 0.003, skew -0.707107, shift -0.039284. Lower: y = 2.484138 - shift
# = 2.523421, c = cbrt(1 + skew * y) = cbrt(-0.784328) = -0.922216, w = 3 * y / (c *
# c + c + 1) = 8.155272, bound -0.030. Upper: y = -2.444854, c = cbrt(2.728773) =
# 1.397406, w = -1.686049, bound 0.026.
def test_the_calibration_compares_each_scenario_with_steady_market_seed_by_seed(
    tmp_path: Path,
):
    report = report_of(calibration_runs(), tmp_path)

    calibration = report.split("## Calibration\n\n")[1].split("\n\n")[1].splitlines()
    disclosure = report.split("## Disclosure effect\n\n")[1].split("\n\n")[1]
    assert calibration == [
        "| Scenario | Worlds | Unscorable | Seeds compared | Calibration score "
        "| Against steady market | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound | Hard enough | Direction |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| scenario-a | 3 | 0 | 3 | 0.880 | -0.070 | 0.006 | -0.095 | -0.045 | yes "
        "| not measured |",
        "| scenario-b | 3 | 0 | 3 | 0.950 | 0.000 | 0.006 | -0.025 | 0.025 | no "
        "| not measured |",
        "| scenario-c | 3 | 0 | 3 | 0.900 | -0.050 | 0.006 | -0.075 | -0.025 "
        "| undecided | not measured |",
        "| steady-market | 3 | 0 | 3 | 0.950 | - | - | - | - | - | not measured |",
    ]
    assert disclosure.splitlines()[2:] == [
        "| scenario-a | ranges of hidden groups disclosed "
        "| buffered_informed_optimizer | buffered_rolling_optimizer | 3 | 0.017 "
        "| 0.003 | -0.030 | 0.026 |"
    ]


# Mean -0.050, standard deviation 0.01, standard error 0.01 / sqrt(3) = 0.005774,
# t(2) = 4.303, half-width 4.303 * 0.005774 = 0.024843: from -0.074843 to -0.025157.
def test_a_comparison_gives_its_mean_standard_error_and_95_percent_bounds():
    differences = [Decimal("-0.05"), Decimal("-0.04"), Decimal("-0.06")]

    assert comparison_cells(differences) == ["-0.050", "0.006", "-0.075", "-0.025"]


# Mean -0.03 and deviations -0.03, -0.01, -0.01, 0.01, 0.04. The moments m2 =
# 0.0028 / 5 = 0.00056 and m3 = 0.000036 / 5 = 0.0000072 give the skew
# m3 / m2 ** 1.5 = 0.0000072 / 0.000013252 = 0.543313. The standard deviation is
# sqrt(0.0028 / 4) = 0.026458, the standard error 0.026458 / sqrt(5) = 0.011832.
# With t(4) = 2.776445, t / sqrt(5) = 1.241664 and the shift 0.543313 / 30 =
# 0.018110. Lower: y = 1.241664 - 0.018110 = 1.223554, c = cbrt(1 + 0.543313 * y)
# = cbrt(1.664773) = 1.185182, w = 3 * y / (c * c + c + 1) = 3.670662 / 3.589838
# = 1.022514, bound -0.03 - 0.026458 * 1.022514 = -0.057053. Upper: y = -1.241664
# - 0.018110 = -1.259774, c = cbrt(0.315548) = 0.680803, w = -3.779322 / 2.144296
# = -1.762500, bound -0.03 + 0.026458 * 1.762500 = 0.016632. The Student interval,
# -0.03 less and plus 2.776445 * 0.011832 = 0.032851, would read -0.063 and 0.003.
def test_a_comparison_of_skewed_differences_corrects_its_interval_for_the_skew():
    differences = [
        Decimal(value) for value in ("-0.06", "-0.04", "-0.04", "-0.02", "0.01")
    ]

    assert comparison_cells(differences) == ["-0.030", "0.012", "-0.057", "0.017"]


# Steady market 0.95 in seeds 0 to 19; the scenario 0.90 in seeds 0 to 15 and 0.95
# in seeds 16 to 19. The differences: 16 of -0.05 and 4 of 0, mean -0.04, deviations
# -0.01 and 0.04, m2 = (16 * 0.0001 + 4 * 0.0016) / 20 = 0.0004, m3 = (16 * -0.000001
# + 4 * 0.000064) / 20 = 0.000012, skew 0.000012 / 0.0004 ** 1.5 = 1.5. Standard
# deviation sqrt(0.008 / 19) = 0.020520, standard error 0.004588. With t(19) =
# 2.093024, t / sqrt(20) = 0.468014 and the shift 1.5 / 120 = 0.0125. Lower: y =
# 0.455514, c = cbrt(1.683272) = 1.189556, w = 1.366543 / 3.604598 = 0.379111, bound
# -0.04 - 0.020520 * 0.379111 = -0.048. Upper: y = -0.480514, c = cbrt(0.279228) =
# 0.653612, w = -1.441543 / 2.080820 = -0.692776, bound -0.04 + 0.020520 * 0.692776 =
# -0.026, above -0.03, so undecided. The Student interval, -0.04 less and plus
# 2.093024 * 0.004588 = 0.009604, would read -0.050 to -0.030 and yes.
def test_a_report_of_skewed_differences_names_its_interval_and_its_verdict(
    tmp_path: Path,
):
    steady = crossing_runs({"buffered_rolling_optimizer": (850,) * 20})
    scenario = crossing_runs({"buffered_rolling_optimizer": (800,) * 16 + (850,) * 4})
    runs = steady + [
        replace(run, scenario="scenario-a", scenario_id="a1") for run in scenario
    ]
    report = report_of(runs, tmp_path)

    calibration = report.split("## Calibration\n\n")[1].split("\n\n")
    assert (
        "The 95 percent interval of every comparison is the Student interval with the "
        "correction for skew of Hall (1992), and the Student interval itself when the "
        "differences have no skew."
    ) in calibration[0]
    assert calibration[1].splitlines()[2] == (
        "| scenario-a | 20 | 0 | 20 | 0.910 | -0.040 | 0.005 | -0.048 | -0.026 "
        "| undecided | not measured |"
    )


def test_a_comparison_of_one_seed_has_no_standard_error_and_no_bounds():
    assert comparison_cells([Decimal("-0.05")]) == ["-0.050", "-", "-", "-"]


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(difference_lists)
def test_the_interval_holds_the_mean_and_gives_the_verdict(differences: list[Decimal]):
    lower, upper = interval_of(differences)
    verdict = hard_enough_of(differences)

    assert lower <= statistics.mean(differences) <= upper
    assert (verdict == "yes") == (upper <= Decimal("-0.03"))
    assert (verdict == "no") == (upper > Decimal("-0.03") and lower >= Decimal("-0.03"))


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(
    st.lists(score_differences, min_size=2, max_size=20),
    st.randoms(use_true_random=False),
)
def test_the_interval_is_the_same_in_any_order_of_the_seeds(
    differences: list[Decimal], random: Random
):
    reordered = random.sample(differences, len(differences))

    assert interval_of(reordered) == interval_of(differences)


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(score_differences, st.integers(min_value=2, max_value=20))
def test_the_interval_of_one_constant_difference_is_that_value_with_width_0(
    difference: Decimal, count: int
):
    assert interval_of([difference] * count) == (difference, difference)


# Seed 2: the reference makes -300 against -100. Seed 3: a solve of the reference has
# no solution, so the rolling optimizer at 2000 there has no score.
def test_a_world_whose_reference_has_a_solve_without_a_solution_is_unscorable(
    tmp_path: Path,
):
    runs = [
        replace(run, solves_without_solution=1, largest_gap=0.35)
        if (run.agent, run.seed) == ("reference", 3)
        else replace(run, profit=Decimal(2000))
        if (run.agent, run.seed) == ("rolling_optimizer", 3)
        else replace(run, profit=Decimal(-300))
        if (run.agent, run.seed) == ("reference", 2)
        else run
        for run in hand_runs()
        if run.seed < 4
    ]
    folder = write_report(tmp_path, runs, [], PROVENANCE, datetime(2026, 10, 12, 10))
    lines = (folder / "report.md").read_text().splitlines()
    with (folder / "runs.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))

    assert (
        "- Worlds: 4 played, 2 unscorable: 1 where the reference makes no more than "
        "no decisions, 1 where a solve of the reference has no solution"
    ) in lines
    assert (
        "| steady-market | reference | integer | 2 | 1.000 | 1.000 | 1.000 | 1.000 "
        "| - |"
    ) in lines
    assert [row["normalized_score"] for row in rows if row["seed"] == "3"] == [""] * 7


# Seed 2: the reference makes -100, as no decisions does, so the denominator of every
# score is 0. Seed 3: a solve of the reference has no solution. The rolling optimizer
# makes the most of the limited optimizers in both, 800 and 2000.
def test_the_report_lists_each_unscorable_world_with_its_profits(tmp_path: Path):
    runs = [
        replace(run, solves_without_solution=1)
        if (run.agent, run.seed) == ("reference", 3)
        else replace(run, profit=Decimal(2000))
        if (run.agent, run.seed) == ("rolling_optimizer", 3)
        else replace(run, profit=Decimal(-100))
        if (run.agent, run.seed) == ("reference", 2)
        else run
        for run in hand_runs()
        if run.seed < 4
    ]
    report = report_of(runs, tmp_path)

    section = report.split("## Unscorable worlds\n\n")[1].split("\n\n## ")[0]
    assert section.splitlines() == [
        UNSCORABLE_RULE,
        "",
        "| Scenario | Seed | Cause | No decisions | Reference | Best limited profit "
        "| Its optimizer |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| steady-market | 2 | the reference makes no more than no decisions | -100 "
        "| -100 | 800 | rolling_optimizer |",
        "| steady-market | 3 | a solve of the reference has no solution | -100 | 900 "
        "| 2000 | rolling_optimizer |",
    ]


def test_a_report_without_an_unscorable_world_says_so(tmp_path: Path):
    runs = [run for run in hand_runs() if run.seed < 4]
    report = report_of(runs, tmp_path)

    assert f"## Unscorable worlds\n\n{UNSCORABLE_RULE}\n\nNone.\n" in report


# A = (0.9, 0.1) and B = (0.1, 0.9): the best of each world is 0.9.
def test_the_best_limited_score_of_each_world_is_its_highest_score():
    runs = crossing_runs(
        {"full_horizon_optimizer": (800, 0), "rolling_optimizer": (0, 800)}
    )

    best = best_scores(runs, scores_of(runs), LIMITED_OPTIMIZERS)

    assert best == {0: Decimal("0.9"), 1: Decimal("0.9")}


# Steady market: the buffered rolling optimizer 0.95 and 0.96. The crossing scenario:
# A = (0.9, 0.1) and B = (0.1, 0.9), best 0.9 in each world, and the buffered rolling
# optimizer 0.8 in both, so -0.15 and -0.16 against steady market, mean -0.155,
# standard error 0.01 / sqrt(2) / sqrt(2) = 0.005, and t(1) * 0.005 = 12.706 * 0.005 =
# 0.0635: from -0.219 to -0.091, yes. The best of each world would read -0.055, from
# -0.119 to 0.009, undecided.
def test_the_calibration_reads_the_buffered_rolling_optimizer_whoever_wins_a_world(
    tmp_path: Path,
):
    steady = crossing_runs({"buffered_rolling_optimizer": (850, 860)})
    crossing = crossing_runs(
        {
            "full_horizon_optimizer": (800, 0),
            "rolling_optimizer": (0, 800),
            "buffered_rolling_optimizer": (700, 700),
        }
    )
    runs = steady + [
        replace(run, scenario="crossing", scenario_id="c1") for run in crossing
    ]
    report = report_of(runs, tmp_path)

    calibration = report.split("## Calibration\n\n")[1].split("\n\n")
    assert calibration[0] == (
        "The calibration reads one limited optimizer, fixed before the run: the "
        "buffered rolling optimizer. Its gap in a world is the profit of the reference "
        "less its profit. The calibration score of a world is 1 less that gap over the "
        "denominator of steady market in the same seed, the profit of the reference "
        "less that of no decisions there; in steady market it is the normalized score "
        "of the optimizer. A loss that the reference and the optimizer share leaves it "
        "unchanged, and so do the denominator of the scenario and the other limited "
        "optimizers. The difficulty pairs the calibration scores of each seed, so the "
        "differences of the seeds are independent, and the standard error and the 95 "
        "percent interval of the verdict cover their mean. The 95 percent interval of "
        "every comparison is the Student interval with the correction for skew of Hall "
        "(1992), and the Student interval itself when the differences have no skew. "
        "Each interval covers its own scenario: at a mean difference of -0.03, about 1 "
        "scenario in 20 still reads yes or no. A scenario whose reading holds "
        "foresight reads foresight and has no verdict: its gap holds what the "
        "reference knows of a disruption before a limited optimizer sees it. A "
        "scenario reads incomplete when a seed it plays has no calibration score in it "
        "or in steady market: a world has none when a solve of its reference has no "
        "solution, and a seed has none when its world of steady market is unscorable. "
        "The scores give the mean of each optimizer without an interval; the optimizer "
        "of the highest mean is chosen on the seeds of the report."
    )
    assert calibration[1].splitlines()[2:] == [
        "| crossing | 2 | 0 | 2 | 0.800 | -0.155 | 0.005 | -0.219 | -0.091 | yes "
        "| not measured |",
        "| steady-market | 2 | 0 | 2 | 0.955 | - | - | - | - | - | not measured |",
    ]


# The informed runs at 1.01 and 1.2 score (0.9, 0.2) and (0.1, 0.9), the rolling
# ones (0.1, 0.9) and (0.7, 0.1). The disclosure effect reads the two at 1.2: 0.1 -
# 0.7 = -0.6 and 0.9 - 0.1 = 0.8, mean 0.1, standard deviation 1.4 / sqrt(2) =
# 0.98995, standard error 0.7, and t(1) * 0.7 = 12.706205 * 0.7 = 8.894343: from
# -8.794 to 8.994. The better run of each side would read 0.2 and 0, mean 0.1,
# standard error 0.1.
def test_the_disclosure_effect_pairs_the_informed_and_rolling_optimizers_at_1_2(
    tmp_path: Path,
):
    runs = [
        replace(run, scenario="hidden-groups", scenario_id="h1")
        for run in crossing_runs(
            {
                "rolling_optimizer": (0, 800),
                "buffered_rolling_optimizer": (600, 0),
                "informed_optimizer": (800, 100),
                "buffered_informed_optimizer": (0, 800),
            }
        )
    ]
    report = report_of(runs, tmp_path)

    section = report.split("## Disclosure effect\n\n")[1].split("\n\n## ")[0]
    assert (
        "The disclosure effect is, per seed, the score of the informed optimizer at "
        "the terminal value factor 1.2 less that of the buffered rolling optimizer, "
        "the rolling optimizer at the same factor. It is the response of this "
        "heuristic policy to the disclosed ranges, and it can be negative. Both "
        "policies are fixed before the run, so the standard error covers the mean of "
        "the differences of the seeds. Every disclosure effect is a diagnostic"
    ) in section
    assert section.splitlines() == [
        DISCLOSURE_RULE,
        "",
        "| Scenario | Treatment | Informed run | Rolling run | Worlds "
        "| Disclosure effect | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| hidden-groups | ranges of hidden groups disclosed "
        "| buffered_informed_optimizer | buffered_rolling_optimizer | 2 | 0.100 "
        "| 0.700 | -8.794 | 8.994 |",
    ]


# The informed runs at 1.2 score (0.6, 0.7), the buffered rolling ones (0.8, 0.85): a
# disclosure effect of -0.2 and -0.15, mean -0.175, standard error 0.05 / sqrt(2) /
# sqrt(2) = 0.025, and t(1) * 0.025 = 12.706205 * 0.025 = 0.317655: from -0.493 to
# 0.143.
def test_a_negative_disclosure_effect_stays_negative(tmp_path: Path):
    runs = [
        replace(run, scenario="forecasts", scenario_id="f1")
        for run in crossing_runs(
            {
                "rolling_optimizer": (800, 600),
                "buffered_rolling_optimizer": (700, 750),
                "informed_optimizer": (600, 700),
                "buffered_informed_optimizer": (500, 600),
            }
        )
    ]
    report = report_of(runs, tmp_path)

    section = report.split("## Disclosure effect\n\n")[1].split("\n\n## ")[0]
    assert section.splitlines()[-1].endswith("| 2 | -0.175 | 0.025 | -0.493 | 0.143 |")


# One seed: the informed runs score 0.9 and the rolling ones 0.8, a disclosure effect
# of 0.1 with no standard error and no bounds.
def test_a_disclosure_effect_of_one_seed_has_no_standard_error_and_no_bounds(
    tmp_path: Path,
):
    runs = [
        replace(run, scenario="hidden-groups", scenario_id="h1")
        for run in crossing_runs(
            {
                "rolling_optimizer": (700,),
                "buffered_rolling_optimizer": (700,),
                "informed_optimizer": (800,),
                "buffered_informed_optimizer": (800,),
            }
        )
    ]
    report = report_of(runs, tmp_path)

    rule, table = report.split("## Disclosure effect\n\n")[1].split("\n\n")[:2]
    assert rule.endswith(
        "Every disclosure effect is a diagnostic; one of a single seed has no standard "
        "error and no bounds."
    )
    assert table.splitlines()[-1].endswith("| 1 | 0.100 | - | - | - |")


def test_a_report_without_informed_runs_lists_no_disclosure_effect(tmp_path: Path):
    report = report_of(hand_runs(), tmp_path)

    assert f"## Disclosure effect\n\n{DISCLOSURE_RULE}\n\nNone.\n" in report


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(factor_profits, st.randoms(use_true_random=False))
def test_the_disclosure_effect_is_the_same_whatever_the_runs_at_1_01_make(
    profits: list[list[int]], random: Random
):
    redrawn = [
        [random.randint(-100, 900), seed[1], random.randint(-100, 900), seed[3]]
        for seed in profits
    ]
    random.shuffle(redrawn)

    assert disclosure_of(redrawn) == disclosure_of(profits)


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(seed_profits, st.randoms(use_true_random=False))
def test_the_calibration_is_the_same_in_any_order_of_the_seeds(
    profits: list[tuple[list[int], list[int]]], random: Random
):
    shuffled = list(profits)
    random.shuffle(shuffled)

    assert calibration_of(limited_runs(shuffled)) == calibration_of(
        limited_runs(profits)
    )


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(seed_profits, st.randoms(use_true_random=False))
def test_the_calibration_is_the_same_whatever_the_other_limited_optimizers_make(
    profits: list[tuple[list[int], list[int]]], random: Random
):
    redrawn = [
        (
            [random.randint(-100, 900) for _ in range(4)] + steady[4:],
            [random.randint(-100, 900) for _ in range(4)] + scenario[4:],
        )
        for steady, scenario in profits
    ]

    assert calibration_of(limited_runs(redrawn)) == calibration_of(
        limited_runs(profits)
    )


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(seed_profits, st.lists(st.integers(0, 3000), min_size=6, max_size=6))
def test_the_verdict_is_the_same_after_a_loss_the_reference_and_the_optimizers_share(
    profits: list[tuple[list[int], list[int]]], losses: list[int]
):
    verdict = verdict_cells(limited_runs(profits))

    assert verdict_cells(losing_runs(profits, losses, shared=False)) == verdict
    assert verdict_cells(losing_runs(profits, losses, shared=True)) == verdict


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(seed_profits, st.lists(st.integers(1, 500), min_size=12, max_size=12))
def test_the_verdict_is_the_same_with_a_sixth_limited_optimizer_worse_in_every_world(
    profits: list[tuple[list[int], list[int]]], shortfalls: list[int]
):
    runs = limited_runs(profits)
    sixth = [
        replace(
            run, agent="sixth", profit=min(sides[side]) - shortfalls[2 * seed + side]
        )
        for seed, sides in enumerate(profits)
        for side, run in enumerate(
            run for run in runs if (run.seed, run.agent) == (seed, "reference")
        )
    ]
    with patch.object(report, "LIMITED_OPTIMIZERS", (*LIMITED_OPTIMIZERS, "sixth")):
        with_sixth = calibration_of(runs + sixth)

    assert with_sixth == calibration_of(runs)


# The fixed policy scores 0.7 in steady market and 0.67 in the scenario on the mean,
# each with a spread of 0.03, on top of a world effect of spread 0.05 that both sides
# of a seed share. The difference of a seed is normal with a mean of -0.03, where the
# Student interval covers the mean in 95 percent of the campaigns and misses it on
# each side in 2.5 percent; the correction for skew reads a skew near 0.
@pytest.mark.slow
@pytest.mark.parametrize("seeds", [5, 20])
def test_the_verdict_on_the_fixed_policy_keeps_its_95_percent_on_normal_differences(
    seeds: int,
):
    generator = numpy.random.default_rng(20261020)
    world = generator.normal(0, 0.05, (CAMPAIGNS, seeds))
    steady = world + generator.normal(0.7, SPREAD, (CAMPAIGNS, seeds))
    scenario = world + generator.normal(0.67, SPREAD, (CAMPAIGNS, seeds))

    shares = verdict_shares(scenario - steady)

    assert abs(shares["undecided"] - 0.95) <= COVERAGE_TOLERANCE
    assert abs(shares["yes"] - 0.025) <= SIDE_TOLERANCE
    assert abs(shares["no"] - 0.025) <= SIDE_TOLERANCE


# The fixed policy scores 0.7 in steady market with a spread of 0.01, and falls short
# of 0.7 in the scenario by an exponential shortfall of mean 0.03, so the difference
# of a seed has a mean of -0.03 and a skew of about -1.7. An independent run of the
# interval as Hall (1992) states it, in floats with numpy, over 2000000 campaigns of
# 20 seeds (seed 20261021), reads yes in 1.739 percent of them, no in 4.269 and
# undecided in 93.992; the Student interval reads no in 6.4 percent. Each share of
# the code is within three of its Monte Carlo standard errors of the one of that run.
@pytest.mark.slow
def test_the_interval_keeps_its_coverage_on_each_side_of_skewed_differences():
    generator = numpy.random.default_rng(20261020)
    steady = generator.normal(0.7, 0.01, (CAMPAIGNS, 20))
    scenario = 0.7 - generator.exponential(SPREAD, (CAMPAIGNS, 20))

    shares = verdict_shares(scenario - steady)

    for verdict, expected in SKEWED_SHARES.items():
        tolerance = 3 * math.sqrt(expected * (1 - expected) / CAMPAIGNS)
        assert abs(shares[verdict] - expected) <= tolerance


# One steady market policy at 0.7 and five scenario policies that draw apart at one
# mean, 0.67, so every policy and the best fixed one differ from steady market by
# -0.03 on the mean. A policy fixed before the seeds keeps the 95 percent; the policy of
# the highest mean over the same seeds lifts its difference and reads no in about 8
# percent of the campaigns.
@pytest.mark.slow
@pytest.mark.parametrize("seeds", [5, 20])
def test_the_policy_of_the_highest_mean_over_the_seeds_loses_its_95_percent(
    seeds: int,
):
    generator = numpy.random.default_rng(20261019)
    steady = generator.normal(0.7, SPREAD, (CAMPAIGNS, seeds))
    scenario = generator.normal(0.67, SPREAD, (CAMPAIGNS, 5, seeds))
    highest = scenario.mean(axis=2).argmax(axis=1)

    fixed = verdict_shares(scenario[:, 0, :] - steady)
    chosen = verdict_shares(scenario[numpy.arange(CAMPAIGNS), highest, :] - steady)

    assert abs(fixed["undecided"] - 0.95) <= COVERAGE_TOLERANCE
    assert chosen["undecided"] < 0.95 - COVERAGE_TOLERANCE
    assert chosen["no"] > 0.025 + SIDE_TOLERANCE


# Steady market in seeds 0 and 1: no decisions 0, the reference 1000000 and the
# buffered rolling optimizer 979000, a gap of 21000, G / D = 0.021. Scenario a: the
# reference 620000, D' = 0.62 D, and the optimizer 599000, the same gap. Scenario b:
# the reference 450000, D' = 0.45 D, and the optimizer 429000, the same gap. Scenario
# c: D' = 0.45 D and the optimizer 419000, a gap 10000 larger. The calibration score is
# 1 - gap / 1000000: 0.979 in a and b, as in steady market, and 0.969 in c. So a and b
# read 0.000 and c -0.010, each the same in both seeds, an interval of width 0, and no.
# The normalized scores would read 599000 / 620000 - 0.979 = -0.013, 429000 / 450000
# - 0.979 = -0.026 and 419000 / 450000 - 0.979 = -0.048, the last yes.
def test_a_smaller_denominator_with_the_same_gap_leaves_the_verdict_at_no():
    runs: list[PlayedRun] = []
    for seed in (0, 1):
        runs += policy_world("steady-market", seed, 0, 1000000, 979000)
        runs += policy_world("scenario-a", seed, 0, 620000, 599000)
        runs += policy_world("scenario-b", seed, 0, 450000, 429000)
        runs += policy_world("scenario-c", seed, 0, 450000, 419000)

    assert calibration_rows(runs) == [
        "| scenario-a | 2 | 0 | 2 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 | no "
        "| not measured |",
        "| scenario-b | 2 | 0 | 2 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 | no "
        "| not measured |",
        "| scenario-c | 2 | 0 | 2 | 0.969 | -0.010 | 0.000 | -0.010 | -0.010 | no "
        "| not measured |",
        "| steady-market | 2 | 0 | 2 | 0.979 | - | - | - | - | - | not measured |",
    ]


# Steady market tied at 0.90, the scenario apart: every optimizer is 0.03 worse on the
# mean. The buffered rolling optimizer scores 0.90, 0.84, 0.855, 0.87 and 0.885 in seeds
# 0 to 4, so the differences are 0, -0.06, -0.045, -0.03 and -0.015: mean -0.03,
# deviations of squares 2 * (0.0009 + 0.000225) = 0.00225, standard deviation
# sqrt(0.00225 / 4) = 0.023717, standard error 0.010607, no skew. With t(4) = 2.776445
# the half-width is 0.029449: from -0.059 to -0.001, undecided. The best of each world
# would read 0.90 - 0.90 = 0 in every seed and no.
def test_5_optimizers_each_0_03_worse_but_apart_read_undecided():
    runs: list[PlayedRun] = []
    for seed in range(5):
        runs += tied_world("steady-market", seed, 800)
        runs += apart_world("scenario-a", seed)

    assert calibration_rows(runs) == [
        "| scenario-a | 5 | 0 | 5 | 0.870 | -0.030 | 0.011 | -0.059 | -0.001 "
        "| undecided | not measured |",
        "| steady-market | 5 | 0 | 5 | 0.900 | - | - | - | - | - | not measured |",
    ]


# Steady market apart, the scenario tied at 0.87: no optimizer changes its mean. The
# differences are 0.87 less 0.90, 0.84, 0.855, 0.87 and 0.885: -0.03, 0.03, 0.015, 0
# and -0.015, mean 0, the deviations of the test above: from -0.029 to 0.029, no. The
# best of each world would read 0.87 - 0.90 = -0.03 in every seed and yes.
def test_5_optimizers_apart_in_steady_market_and_tied_unchanged_read_no():
    runs: list[PlayedRun] = []
    for seed in range(5):
        runs += apart_world("steady-market", seed)
        runs += tied_world("scenario-a", seed, 770)

    assert calibration_rows(runs) == [
        "| scenario-a | 5 | 0 | 5 | 0.870 | 0.000 | 0.011 | -0.029 | 0.029 | no "
        "| not measured |",
        "| steady-market | 5 | 0 | 5 | 0.870 | - | - | - | - | - | not measured |",
    ]


# Steady market in seeds 0 to 19: no decisions -100, the reference 900 and the buffered
# rolling optimizer 800, a calibration score of 0.9. Both scenarios: the optimizer 750
# in seeds 0 to 16, a gap of 150, 0.85, so -0.05 against steady market. In seeds 17 to
# 19 of scenario a the reference makes -200 against -100, unscorable, and the optimizer
# -300: a gap of 100, 0.9, a difference of 0. The 20 differences, 17 of -0.05 and 3 of
# 0: mean -0.0425, deviations -0.0075 and 0.0425, m2 = (17 * 0.00005625 + 3 *
# 0.00180625) / 20 = 0.00031875, m3 = (17 * -0.000000421875 + 3 * 0.000076765625) / 20
# = 0.0000111563, skew 0.0000111563 / 0.00031875 ** 1.5 = 1.960392, standard deviation
# sqrt(0.006375 / 19) = 0.018317, standard error 0.004096. With t(19) = 2.093024,
# t / sqrt(20) = 0.468014 and the shift 1.960392 / 120 = 0.016337. Lower: y = 0.451677,
# c = cbrt(1.885466) = 1.235476, w = 1.355032 / 3.761877 = 0.360228, bound -0.0425 -
# 0.018317 * 0.360228 = -0.049. Upper: y = -0.484351, c = cbrt(0.050482) = 0.369639,
# w = -1.453052 / 1.506270 = -0.964670, bound -0.0425 + 0.018317 * 0.964670 = -0.025:
# undecided. The calibration score of a is (17 * 0.85 + 3 * 0.9) / 20 = 0.8575, 0.858
# half to even. In seeds 17 to 19 of scenario b a solve of the reference has no
# solution: those worlds have no calibration score, so b reads 17 seeds of -0.05 and
# incomplete. Dropping the three seeds, as a normalized score does, reads yes for both.
def test_a_scenario_unscorable_in_3_of_20_seeds_reads_by_the_cause_of_each_seed():
    runs: list[PlayedRun] = []
    for seed in range(20):
        runs += policy_world("steady-market", seed, -100, 900, 800)
        if seed < 17:
            runs += policy_world("scenario-a", seed, -100, 900, 750)
            runs += policy_world("scenario-b", seed, -100, 900, 750)
        else:
            runs += policy_world("scenario-a", seed, -100, -200, -300)
            runs += [
                replace(run, solves_without_solution=1)
                if run.agent == "reference"
                else run
                for run in policy_world("scenario-b", seed, -100, 900, 750)
            ]

    assert calibration_rows(runs) == [
        "| scenario-a | 20 | 3 | 20 | 0.858 | -0.042 | 0.004 | -0.049 | -0.025 "
        "| undecided | not measured |",
        "| scenario-b | 20 | 3 | 17 | 0.850 | -0.050 | 0.000 | -0.050 | -0.050 "
        "| incomplete | not measured |",
        "| steady-market | 20 | 0 | 20 | 0.900 | - | - | - | - | - | not measured |",
    ]


# Steady market in seeds 0 to 19: no decisions 0, the reference 1000000 and the
# buffered rolling optimizer 979000. The scenario is the same in seeds 0 to 18; in seed
# 19 no decisions makes 0, the reference 1000, a denominator of 1000, and the optimizer
# -20000. Its gap is 21000, as in steady market, so its calibration score is 0.979 and
# every difference is 0: no. Its normalized score would be -20, a difference of
# -20.979 that moves the mean of 20 seeds to -1.049.
def test_a_world_of_denominator_1000_and_a_gain_of_minus_20000_moves_no_mean():
    runs: list[PlayedRun] = []
    for seed in range(20):
        runs += policy_world("steady-market", seed, 0, 1000000, 979000)
        if seed < 19:
            runs += policy_world("scenario-a", seed, 0, 1000000, 979000)
    runs += policy_world("scenario-a", 19, 0, 1000, -20000)

    assert calibration_rows(runs)[0] == (
        "| scenario-a | 20 | 0 | 20 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 | no "
        "| not measured |"
    )


# Steady market in seeds 0 and 1: no decisions -100, the reference 900 and the buffered
# rolling optimizer 800, 0.9. In each scenario the optimizer makes 300, a gap of 600,
# 0.4, so -0.5 in both seeds. supplier-outage (foresight and overload), price-change
# (adaptation and foresight) and notice (information, foresight and overload) have no
# verdict; demand-surge (overload) reads yes.
def test_a_scenario_whose_reading_holds_foresight_has_no_verdict():
    runs: list[PlayedRun] = []
    for seed in (0, 1):
        runs += policy_world("steady-market", seed, -100, 900, 800)
        for scenario in ("supplier-outage", "price-change", "notice", "demand-surge"):
            runs += policy_world(scenario, seed, -100, 900, 300)

    rows = calibration_rows(runs)

    assert rows[0].startswith(
        "| demand-surge | 2 | 0 | 2 | 0.400 | -0.500 | 0.000 | -0.500 | -0.500 | yes |"
    )
    assert rows[1].startswith(
        "| notice | 2 | 0 | 2 | 0.400 | -0.500 | 0.000 | -0.500 | -0.500 | foresight |"
    )
    assert rows[2].startswith(
        "| price-change | 2 | 0 | 2 | 0.400 | -0.500 | 0.000 | -0.500 | -0.500 "
        "| foresight |"
    )
    assert rows[4].startswith(
        "| supplier-outage | 2 | 0 | 2 | 0.400 | -0.500 | 0.000 | -0.500 | -0.500 "
        "| foresight |"
    )


# Steady market in seeds 0 to 19: no decisions 0, the reference 1000000 and the
# buffered rolling optimizer 979000, 0.979. Scenario a: the reference 450000 and the
# optimizer 429000, the same gap, 0.979. Scenario b: the optimizer 949000, 0.949, so
# -0.030 in every seed and yes, while the rolling optimizer makes 1000000 and holds a
# best limited score of 1 above the 0.979 of steady market. Scenario c: the gap of
# steady market, and a solve of the reference without a solution in seeds 17 to 19:
# 17 seeds compared, incomplete. Scenario d: the gap of steady market, and in seed 19 a
# denominator of 1000 and the optimizer at -20000, a gap of 21000: 0.979, no.
def test_a_report_of_the_4_cases_gives_the_verdict_of_each_and_its_rule(tmp_path: Path):
    runs: list[PlayedRun] = []
    for seed in range(20):
        runs += policy_world("steady-market", seed, 0, 1000000, 979000)
        runs += policy_world("scenario-a", seed, 0, 450000, 429000)
        runs += policy_world(
            "scenario-b", seed, 0, 1000000, 949000, rolling_optimizer=1000000
        )
        runs += [
            replace(run, solves_without_solution=1)
            if run.agent == "reference" and seed >= 17
            else run
            for run in policy_world("scenario-c", seed, 0, 1000000, 979000)
        ]
        if seed < 19:
            runs += policy_world("scenario-d", seed, 0, 1000000, 979000)
    runs += policy_world("scenario-d", 19, 0, 1000, -20000)
    report = report_of(runs, tmp_path)

    rule, table = report.split("## Calibration\n\n")[1].split("\n\n")[:2]
    assert rule.startswith(
        "The calibration reads one limited optimizer, fixed before the run: the "
        "buffered rolling optimizer. Its gap in a world is the profit of the reference "
        "less its profit. The calibration score of a world is 1 less that gap over the "
        "denominator of steady market in the same seed"
    )
    assert "reads foresight and has no verdict" in rule
    assert "A scenario reads incomplete when a seed it plays has no calibration" in rule
    assert table.splitlines() == [
        "| Scenario | Worlds | Unscorable | Seeds compared | Calibration score "
        "| Against steady market | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound | Hard enough | Direction |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| scenario-a | 20 | 0 | 20 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 | no "
        "| not measured |",
        "| scenario-b | 20 | 0 | 20 | 0.949 | -0.030 | 0.000 | -0.030 | -0.030 | yes "
        "| not measured |",
        "| scenario-c | 20 | 3 | 17 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 "
        "| incomplete | not measured |",
        "| scenario-d | 20 | 0 | 20 | 0.979 | 0.000 | 0.000 | 0.000 | 0.000 | no "
        "| not measured |",
        "| steady-market | 20 | 0 | 20 | 0.979 | - | - | - | - | - | not measured |",
    ]


# No decisions -100 and the reference 900 in every world, so a score is
# (profit + 100) / 1000. The buffered rolling optimizer makes 850 and 860 in steady
# market, 800 and 820 in hidden-groups and 840 and 870 in its visible twin. The effect
# of hiding: 0.90 - 0.94 = -0.04 and 0.92 - 0.97 = -0.05, mean -0.045, standard error
# 0.00707 / sqrt(2) = 0.005, and t(1) * 0.005 = 0.0635: from -0.109 to 0.019. The
# rolling optimizer makes 900 in the twin, a score of 1, so the best of each side
# would read -0.10 and -0.08.
def test_the_report_gives_the_effect_of_hidden_groups_against_its_visible_twin(
    tmp_path: Path,
):
    buffered = {
        ("steady-market", "s1"): (850, 860),
        ("hidden-groups", "h1"): (800, 820),
        ("hidden-groups-shown", "h2"): (840, 870),
    }
    runs = [
        replace(run, scenario=scenario, scenario_id=scenario_id)
        for (scenario, scenario_id), profits in buffered.items()
        for run in crossing_runs(
            {
                "rolling_optimizer": (900, 900) if scenario_id == "h2" else profits,
                "buffered_rolling_optimizer": profits,
            }
        )
    ]
    report = report_of(runs, tmp_path)

    section = report.split("## Information controls\n\n")[1].split("\n\n## ")[0]
    calibration = report.split("## Calibration\n\n")[1].split("\n\n")[1]
    scenarios = report.split("## Scenarios\n\n")[1].split("\n\n")[0]
    assert (
        "The effect of the treatment is, per seed, the normalized score of the "
        "buffered rolling optimizer, fixed before the run, in the scenario less its "
        "normalized score in the control."
    ) in section
    assert section.splitlines() == [
        INFORMATION_RULE,
        "",
        "| Scenario | Treatment | Control | Control identifier | Held equal | Worlds "
        "| Effect of the treatment | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| hidden-groups | hidden | hidden-groups-shown | h2 | manifest, seeds, "
        "horizon, start, demand shapes, disruptions, forecasts | 2 | -0.045 | 0.005 "
        "| -0.109 | 0.019 |",
    ]
    assert "| hidden-groups | 2 | 0 | 2 | 0.910 | -0.045 |" in calibration
    assert "hidden-groups-shown" not in calibration
    assert "| hidden-groups-shown | h2 |" in scenarios


# A score is (profit + 100) / 1000. The rolling and buffered rolling optimizers score
# alike: steady market 0.95, 0.96, 0.94; hidden-groups 0.90, 0.92, 0.88; its visible
# twin 0.94, 0.95, 0.93; the informed runs of hidden-groups 0.8 at 1.01 and 0.92, 0.93,
# 0.91 at 1.2. Each comparison has a standard deviation of 0.01, a standard error of
# 0.005774 and a half-width of t(2) * 0.005774 = 4.303 * 0.005774 = 0.024843 about its
# mean. The difficulty -0.05, -0.04, -0.06: mean -0.050, from -0.075 to -0.025, so
# undecided. The effect of hiding -0.04, -0.03, -0.05: mean -0.040, from -0.065 to
# -0.015. The disclosure effect 0.02, 0.01, 0.03: mean 0.020, from -0.005 to 0.045.
def test_every_comparison_of_the_report_gives_the_bounds_of_its_95_percent_interval(
    tmp_path: Path,
):
    profits = {
        ("steady-market", "s1"): {"rolling_optimizer": (850, 860, 840)},
        ("hidden-groups-shown", "h2"): {"rolling_optimizer": (840, 850, 830)},
        ("hidden-groups", "h1"): {
            "rolling_optimizer": (800, 820, 780),
            "informed_optimizer": (700, 700, 700),
            "buffered_informed_optimizer": (820, 830, 810),
        },
    }
    runs = [
        replace(run, scenario=scenario, scenario_id=scenario_id)
        for (scenario, scenario_id), agents in profits.items()
        for run in crossing_runs(
            agents | {"buffered_rolling_optimizer": agents["rolling_optimizer"]}
        )
    ]
    report = report_of(runs, tmp_path)

    calibration = report.split("## Calibration\n\n")[1].split("\n\n")[1].splitlines()
    information = report.split("## Information controls\n\n")[1].split("\n\n")[1]
    disclosure = report.split("## Disclosure effect\n\n")[1].split("\n\n")[1]
    assert calibration[:2] == [
        "| Scenario | Worlds | Unscorable | Seeds compared | Calibration score "
        "| Against steady market | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound | Hard enough | Direction |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    assert calibration[2].startswith(
        "| hidden-groups | 3 | 0 | 3 | 0.900 | -0.050 | 0.006 | -0.075 | -0.025 "
        "| undecided |"
    )
    assert information.splitlines()[0].endswith(
        "| Effect of the treatment | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |"
    )
    assert information.splitlines()[2].endswith(
        "| 3 | -0.040 | 0.006 | -0.065 | -0.015 |"
    )
    assert disclosure.splitlines()[0].endswith(
        "| Disclosure effect | Its standard error | Lower 95 percent bound "
        "| Upper 95 percent bound |"
    )
    assert disclosure.splitlines()[2].endswith("| 3 | 0.020 | 0.006 | -0.005 | 0.045 |")


def test_a_report_without_a_scenario_and_its_control_lists_no_information_effect(
    tmp_path: Path,
):
    report = report_of(hand_runs(), tmp_path)

    assert f"## Information controls\n\n{INFORMATION_RULE}\n\nNone.\n" in report


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(seed_profits, st.randoms(use_true_random=False))
def test_the_effect_of_a_treatment_ignores_the_other_limited_optimizers(
    profits: list[tuple[list[int], list[int]]], random: Random
):
    redrawn = [
        (
            [random.randint(-100, 900) for _ in range(4)] + shown[4:],
            [random.randint(-100, 900) for _ in range(4)] + hidden[4:],
        )
        for shown, hidden in profits
    ]

    assert information_of(redrawn) == information_of(profits)


# Steady market: no decisions -100, the reference 900 and the rolling optimizer 800, a
# denominator of 1000, a score of 0.9 and a gap of 100 to the reference. The scenario:
# no decisions -2100, the reference 700 and the rolling optimizer 500, a denominator of
# 2800, a score of 2600 / 2800 = 0.929 and a gap of 200. The score rises by 0.029 while
# the best limited profit falls by 300 and its gap to the reference grows by 100.
def test_a_larger_denominator_raises_the_score_while_profit_and_gap_worsen(
    tmp_path: Path,
):
    runs = world_runs("steady-market", 0, -100, 900, 800)
    runs += world_runs("scenario-a", 0, -2100, 700, 500)
    report = report_of(runs, tmp_path)

    rule, _, against = decision_value_of(report)
    assert rule == DECISION_VALUE_RULE
    assert against.splitlines() == [
        "| Scenario | Worlds | Score against steady market "
        "| Profit against steady market | Gap against steady market "
        "| Denominator against steady market | Reading | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        "| scenario-a | 1 | 0.029 | -300.000 | 100.000 | 1800.000 | not assessed "
        "| No assessment of this scenario. |",
    ]


def test_a_reference_without_the_other_runs_of_its_world_gives_no_outcome():
    no_decisions = hand_run("no_decisions", profit=Decimal(-100))
    reference = hand_run("reference", profit=Decimal(900))
    rolling = hand_run("rolling_optimizer", profit=Decimal(800))

    assert world_outcomes([reference]) == {}
    assert world_outcomes([no_decisions, reference]) == {}
    assert world_outcomes([reference, rolling]) == {}


# Seed 0 holds every run; seed 1 holds no decisions and the reference only, as an index
# cut after the reference whose world then raised.
def test_a_report_of_a_world_without_its_limited_runs_reads_the_other_worlds(
    tmp_path: Path,
):
    runs = [run for run in hand_runs() if run.seed == 0 or run.agent in AGENTS[:2]]
    runs = [run for run in runs if run.seed < 2]

    report = report_of(runs, tmp_path)

    absolute = decision_value_of(report)[1].splitlines()
    assert absolute[2].startswith("| steady-market | 1 | -100.000 | 900.000 |")


# Seed 0: no decisions -100, the reference 900 ships 90 of 100 units, loses 10, buys 500
# and closes 2 periods below the credit limit; the rolling optimizer, best at 800, ships
# 80. Seed 1: no decisions -300, the reference 700 ships all 100 and buys 300; the
# full-horizon optimizer, best at 600, ships 70. Means: no decisions -200, the reference
# 800, the denominator 1000, the best limited profit 700 and its gap 100, fill rates
# 0.95 and 0.75, 5 units lost, 400 bought and 1 period below the credit limit.
def test_the_outcomes_of_a_scenario_are_means_over_its_worlds(tmp_path: Path):
    runs = [
        outcome_run("no_decisions", 0, -100, 0),
        outcome_run("reference", 0, 900, 90, lost=10, bought=500, below=2),
        outcome_run("rolling_optimizer", 0, 800, 80),
        outcome_run("no_decisions", 1, -300, 0),
        outcome_run("reference", 1, 700, 100, bought=300),
        outcome_run("full_horizon_optimizer", 1, 600, 70),
        outcome_run("rolling_optimizer", 1, 100, 10),
    ]
    report = report_of(runs, tmp_path)

    _, absolute, _ = decision_value_of(report)
    assert absolute.splitlines() == [
        "| Scenario | Worlds | No decisions | Reference | Denominator "
        "| Best limited profit "
        "| Gap to the reference | Fill rate of the reference "
        "| Fill rate of the best limited | Units lost by the reference "
        "| Units bought by the reference | Periods below the credit limit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "| steady-market | 2 | -200.000 | 800.000 | 1000.000 | 700.000 | 100.000 "
        "| 0.950 | 0.750 | 5.000 | 400.000 | 1.000 |",
    ]


def test_every_scenario_of_the_library_but_steady_market_has_a_reading():
    names = {path.stem for path in (EXAMPLES / "scenarios").glob("*.json")}
    readings = {reading for reading, _ in DECISION_VALUES.values()}

    assert set(DECISION_VALUES) == names - {"steady-market"}
    assert readings <= {
        "adaptation",
        "adaptation and overload",
        "adaptation and foresight",
        "overload",
        "foresight",
        "foresight and overload",
        "recovery",
        "information",
        "information and overload",
        "information, foresight and overload",
    }
    assert all(evidence.endswith(".") for _, evidence in DECISION_VALUES.values())


@pytest.mark.parametrize("scenario_count", [1, 12])
def test_saved_score_chart_contains_legend_title_and_long_scenario_labels(
    tmp_path: Path, scenario_count: int
):
    original_save = cast(
        Callable[..., None],
        Figure.savefig,  # pyright: ignore[reportUnknownMemberType]
    )
    checked: list[Figure] = []

    def save(figure: Figure, path: Path, **options: object) -> None:
        original_save(figure, path, **options)
        canvas = cast(FigureCanvasAgg, figure.canvas)
        canvas.draw()
        renderer = canvas.get_renderer()
        axes = figure.axes[0]
        artists = [
            *figure.legends,
            axes.title,
            axes.xaxis.label,
            *axes.get_yticklabels(),
        ]
        for artist in artists:
            bounds = artist.get_window_extent(renderer)
            assert bounds.x0 >= figure.bbox.x0 - 1
            assert bounds.y0 >= figure.bbox.y0 - 1
            assert bounds.x1 <= figure.bbox.x1 + 1
            assert bounds.y1 <= figure.bbox.y1 + 1
        checked.append(figure)

    scenarios = [
        (
            f"Scenario {position} with a long description of demand and supply",
            str(position),
        )
        for position in range(scenario_count)
    ]
    provenance = replace(
        PROVENANCE,
        manifest_name="A factory with a long descriptive name " * 4,
    )
    output = tmp_path / "scores.png"
    with patch.object(Figure, "savefig", save):
        report.plot_scores(output, [], {}, scenarios, provenance)

    assert len(checked) == 1
    assert output.read_bytes().startswith(b"\x89PNG")
