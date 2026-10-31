import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from factory_simulator.api.services.examples import EXAMPLES
from stress.controls import INFORMATION_CONTROLS
from stress.playing import append_to_index
from stress.protocol import (
    PROTOCOL,
    CalibrationProtocol,
    EvaluationStart,
    FrozenDefinitions,
    build_analysis_digest,
    build_protocol_line,
    check_development_seeds,
    check_evaluation,
    check_protocol,
    read_evaluation_starts,
    record_evaluation_start,
)
from stress.test_playing import SOLVER_ENVIRONMENT, hand_run

FROZEN = FrozenDefinitions(
    version="0.5.0",
    code="c0de",
    solver_environment=SOLVER_ENVIRONMENT,
    checks="c4ec5",
    analysis="a7a1",
    settings="time_limit=60.0",
    manifest_id="manifest-1",
    scenario_ids={"steady-market": "scenario-1", "cash-squeeze": "scenario-2"},
)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# The modules of the analysis, by their paths under a folder of tests, and their text.
ANALYSIS_MODULES = (
    ("stress/playing.py", "a"),
    ("stress/controls.py", "b"),
    ("stress/report.py", "c"),
    ("stress/test_stress.py", "d"),
    ("factories/client.py", "e"),
)


def test_a_protocol_whose_development_seeds_reach_its_evaluation_seeds_is_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1005),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )

    with pytest.raises(ValueError) as refused:
        check_protocol(protocol)

    assert str(refused.value) == (
        "the evaluation seeds 1000 to 1019 overlap the development seeds 0 to 1004"
    )


def test_a_protocol_without_frozen_definitions_is_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=None,
    )

    with pytest.raises(ValueError) as refused:
        check_protocol(protocol)

    assert str(refused.value) == "the protocol has no frozen definitions"


def test_frozen_definitions_with_an_empty_identifier_are_refused():
    frozen = replace(
        FROZEN,
        code="",
        scenario_ids={"steady-market": "scenario-1", "cash-squeeze": ""},
    )
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=frozen,
    )

    with pytest.raises(ValueError) as refused:
        check_protocol(protocol)

    assert str(refused.value) == (
        "the frozen definitions miss code and the identifier of cash-squeeze"
    )


def test_a_budget_other_than_the_evaluation_seeds_times_the_scenarios_is_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=41,
        frozen=FROZEN,
    )

    with pytest.raises(ValueError) as refused:
        check_protocol(protocol)

    assert str(refused.value) == (
        "the budget of 41 worlds is not 20 seeds times 2 scenarios"
    )


def test_a_development_run_that_reaches_an_evaluation_seed_is_refused():
    check_development_seeds(PROTOCOL, range(1000))

    with pytest.raises(ValueError) as refused:
        check_development_seeds(PROTOCOL, range(1001))

    assert str(refused.value) == (
        "a development run plays the seeds 0 to 1000, which reach the evaluation "
        "seeds 1000 to 1019"
    )


@pytest.mark.parametrize("count", [0, -1])
def test_a_development_run_of_no_seed_is_refused(count: int):
    with pytest.raises(ValueError) as refused:
        check_development_seeds(PROTOCOL, range(count))

    assert str(refused.value) == (
        "a development run plays at least 1 seed; --stress-seeds is 1 or more"
    )


# 23 scenarios of the library and 3 built information controls on 20 seeds.
def test_the_protocol_reserves_seeds_1000_to_1019_for_520_worlds_not_yet_frozen():
    library = list((EXAMPLES / "scenarios").glob("*.json"))
    built = [control for control in INFORMATION_CONTROLS if control.built]

    assert (len(library), len(built)) == (23, 3)
    assert PROTOCOL.evaluation_seeds == range(1000, 1020)
    assert PROTOCOL.development_seeds == range(1000)
    assert PROTOCOL.worlds == 520
    with pytest.raises(ValueError) as refused:
        check_protocol(PROTOCOL)

    assert str(refused.value) == "the protocol has no frozen definitions"


def test_an_evaluation_under_other_definitions_than_the_frozen_ones_is_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    current = replace(
        FROZEN,
        code="c0de2",
        solver_environment="scipy=1.19.0, highs=1.13.0",
        scenario_ids={"steady-market": "scenario-1", "cash-squeeze": "scenario-3"},
    )

    check_evaluation(protocol, FROZEN, [], [])
    with pytest.raises(ValueError) as refused:
        check_evaluation(protocol, current, [], [])

    assert str(refused.value) == (
        "the current definitions differ from the frozen ones in code, "
        "solver_environment and scenario_ids"
    )


# The index holds a development run under old code, which is allowed, a run of seed
# 1000 under the frozen definitions, and three runs of evaluation seeds under others:
# one of old code, one of a scenario identifier the protocol does not freeze and one of
# another solver environment.
def test_an_evaluation_whose_seeds_were_played_under_other_definitions_is_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    frozen_run = hand_run("reference", 1000, scenario_id="scenario-1", version="0.5.0")
    runs = [
        hand_run("reference", 3, code="0ld"),
        frozen_run,
        replace(frozen_run, seed=1001, code="0ld"),
        replace(frozen_run, scenario_id="scenario-9"),
        replace(frozen_run, seed=1002, solver_environment="scipy=1.19.0, highs=1.13.0"),
    ]

    check_evaluation(protocol, FROZEN, runs[:2], [])
    with pytest.raises(ValueError) as refused:
        check_evaluation(protocol, FROZEN, runs, [])

    assert str(refused.value) == (
        "runs of the evaluation seeds under other definitions in the index: 3; a "
        "new evaluation takes seeds no run has read"
    )


# A run of seed 1000 under the frozen definitions but one: its version, code, solver
# environment, settings or scenario identifier. Each of them alone spends the seed.
@pytest.mark.parametrize(
    "changes",
    [
        {"version": "0.4.9"},
        {"code": "0ld"},
        {"solver_environment": "scipy=1.19.0, highs=1.13.0"},
        {"settings": "time_limit=30.0"},
        {"scenario_id": "scenario-9"},
    ],
)
def test_a_run_of_an_evaluation_seed_under_one_other_definition_is_refused(
    changes: dict[str, str],
):
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    frozen_run = hand_run("reference", 1000, scenario_id="scenario-1", version="0.5.0")

    check_evaluation(protocol, FROZEN, [frozen_run], [])
    with pytest.raises(ValueError) as refused:
        check_evaluation(protocol, FROZEN, [replace(frozen_run, **changes)], [])

    assert str(refused.value) == (
        "runs of the evaluation seeds under other definitions in the index: 1; a "
        "new evaluation takes seeds no run has read"
    )


# A start on the evaluation seeds under other code and analysis spends them; a start
# under the frozen definitions is the same evaluation, and a start on other seeds is
# another evaluation.
def test_seeds_of_an_evaluation_started_under_other_definitions_are_refused():
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    other = EvaluationStart(
        time="2026-10-20T10:00:00",
        seeds=range(1000, 1020),
        definitions=replace(FROZEN, code="0ld", analysis="a7a2"),
    )

    check_evaluation(protocol, FROZEN, [], [replace(other, definitions=FROZEN)])
    check_evaluation(protocol, FROZEN, [], [replace(other, seeds=range(1020, 1040))])
    with pytest.raises(ValueError) as refused:
        check_evaluation(protocol, FROZEN, [], [other])

    assert str(refused.value) == (
        "an evaluation of the seeds 1000 to 1019 started at 2026-10-20T10:00:00 under "
        "definitions that differ in code and analysis; a new evaluation takes seeds no "
        "run has read"
    )


# The evaluation under the frozen definitions plays seed 1000, and its index is moved
# away; the evaluation under other code then finds no run in the index, but the start
# of the first evaluation beside it.
def test_an_evaluation_after_its_index_moved_away_is_refused_by_its_recorded_start(
    tmp_path: Path,
):
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    changed = replace(FROZEN, code="c0de2")
    index = tmp_path / "records" / "stress-runs.csv"
    index.parent.mkdir()
    (tmp_path / "moved").mkdir()

    record_evaluation_start(index, protocol, FROZEN, "2026-10-20T10:00:00")
    run = hand_run("reference", 1000, scenario_id="scenario-1", version="0.5.0")
    append_to_index(index, [run])
    index.rename(tmp_path / "moved" / "stress-runs.csv")
    with pytest.raises(ValueError) as refused:
        record_evaluation_start(
            index, replace(protocol, frozen=changed), changed, "2026-10-21T10:00:00"
        )

    assert str(refused.value) == (
        "an evaluation of the seeds 1000 to 1019 started at 2026-10-20T10:00:00 under "
        "definitions that differ in code; a new evaluation takes seeds no run has read"
    )
    assert read_evaluation_starts(tmp_path / "records" / "stress-evaluations.json") == [
        EvaluationStart(
            time="2026-10-20T10:00:00", seeds=range(1000, 1020), definitions=FROZEN
        )
    ]


# A folder other than data/records, without an index yet: the evaluation starts, stops
# and resumes under the frozen definitions.
def test_a_resumed_evaluation_appends_its_start_beside_the_index_it_is_given(
    tmp_path: Path,
):
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    index = tmp_path / "elsewhere" / "records" / "stress-runs.csv"
    index.parent.mkdir(parents=True)

    record_evaluation_start(index, protocol, FROZEN, "2026-10-20T10:00:00")
    record_evaluation_start(index, protocol, FROZEN, "2026-10-20T11:00:00")

    assert read_evaluation_starts(index.with_name("stress-evaluations.json")) == [
        EvaluationStart(time=time, seeds=range(1000, 1020), definitions=FROZEN)
        for time in ("2026-10-20T10:00:00", "2026-10-20T11:00:00")
    ]
    assert [path.name for path in index.parent.iterdir()] == ["stress-evaluations.json"]


# The index holds a run of seed 1001 under old code.
def test_an_evaluation_refused_by_its_index_records_no_start(tmp_path: Path):
    protocol = CalibrationProtocol(
        development_seeds=range(1000),
        evaluation_seeds=range(1000, 1020),
        worlds=40,
        frozen=FROZEN,
    )
    index = tmp_path / "stress-runs.csv"
    run = hand_run("reference", 1001, scenario_id="scenario-1", code="0ld")
    append_to_index(index, [run])

    with pytest.raises(ValueError) as refused:
        record_evaluation_start(index, protocol, FROZEN, "2026-10-20T10:00:00")

    assert str(refused.value) == (
        "runs of the evaluation seeds under other definitions in the index: 1; a "
        "new evaluation takes seeds no run has read"
    )
    assert [path.name for path in tmp_path.iterdir()] == ["stress-runs.csv"]


# The protocol and the checks are no part of the analysis digest.
def test_the_analysis_digest_reads_the_plays_the_controls_and_the_report_in_order(
    tmp_path: Path,
):
    (tmp_path / "stress").mkdir()
    (tmp_path / "factories").mkdir()
    for path, text in ANALYSIS_MODULES:
        (tmp_path / path).write_text(text)
    (tmp_path / "stress" / "protocol.py").write_bytes(b"f")
    (tmp_path / "stress" / "checks.py").write_bytes(b"g")

    assert build_analysis_digest(tmp_path) == sha256_of(
        "".join(f"{sha256_of(text)} {path}\n" for path, text in ANALYSIS_MODULES)
    )


@pytest.mark.parametrize("path", ["factories/client.py", "stress/test_stress.py"])
def test_the_analysis_digest_changes_with_the_plays_of_the_client_and_the_stress_test(
    tmp_path: Path, path: str
):
    (tmp_path / "stress").mkdir()
    (tmp_path / "factories").mkdir()
    for module, text in ANALYSIS_MODULES:
        (tmp_path / module).write_text(text)
    before = build_analysis_digest(tmp_path)
    (tmp_path / path).write_text("changed")

    assert build_analysis_digest(tmp_path) != before


def test_the_protocol_line_names_the_kind_of_run_and_the_split_of_the_seeds():
    development = build_protocol_line(PROTOCOL, evaluation=False)
    evaluation = build_protocol_line(PROTOCOL, evaluation=True)

    assert development == (
        "development; development seeds 0 to 999, evaluation seeds 1000 to 1019"
    )
    assert evaluation == (
        "confirmatory evaluation of the frozen definitions; development seeds 0 to "
        "999, evaluation seeds 1000 to 1019, a budget of 520 worlds"
    )
