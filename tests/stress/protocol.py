import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from stress.playing import (
    PlayedRun,
    RunIdentity,
    build_files_digest,
    identity_of,
    read_index,
)

# The file beside the index that holds the start of every confirmatory evaluation.
EVALUATIONS_FILE = "stress-evaluations.json"


# What a confirmatory evaluation plays under: the version of the package, the digest of
# the code, the solver environment, the digests of the checks and of the analysis, the
# settings, the manifest and the identifier of every scenario by name.
@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenDefinitions:
    version: str
    code: str
    solver_environment: str
    checks: str
    analysis: str
    settings: str
    manifest_id: str
    scenario_ids: dict[str, str]


# The calibration protocol: the seeds of development, the seeds of the one
# confirmatory evaluation, its budget of worlds and the definitions it plays under,
# None until they are frozen.
@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationProtocol:
    development_seeds: range
    evaluation_seeds: range
    worlds: int
    frozen: FrozenDefinitions | None


# The start of a confirmatory evaluation: its time, its evaluation seeds and the
# definitions it plays under.
@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationStart:
    time: str
    seeds: range
    definitions: FrozenDefinitions


# The seeds below 1000 are for development; the 20 seeds from 1000 are for one
# evaluation of the 23 scenarios of the library and the 3 built information controls.
PROTOCOL = CalibrationProtocol(
    development_seeds=range(1000),
    evaluation_seeds=range(1000, 1020),
    worlds=520,
    frozen=None,
)


def seeds_text(seeds: range) -> str:
    return f"{seeds[0]} to {seeds[-1]}"


def joined_text(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


# The digest of the modules of the analysis under a folder of tests: the agents and the
# named measures, the information controls, the report with its estimand and verdicts,
# the stress test, which picks the worlds played twice and the runs of the report, and
# the plays of no decisions and the reference in the client of the tests.
def build_analysis_digest(tests: Path) -> str:
    return build_files_digest(
        tests,
        [
            "stress/playing.py",
            "stress/controls.py",
            "stress/report.py",
            "stress/test_stress.py",
            "factories/client.py",
        ],
    )


# The refusal of a protocol whose development and evaluation seeds overlap, that has no
# frozen definitions, whose frozen definitions hold an empty value or identifier, or
# whose budget is not its evaluation seeds times its scenarios.
def check_protocol(protocol: CalibrationProtocol) -> None:
    development, evaluation = protocol.development_seeds, protocol.evaluation_seeds
    if set(development) & set(evaluation):
        raise ValueError(
            f"the evaluation seeds {seeds_text(evaluation)} overlap the development "
            f"seeds {seeds_text(development)}"
        )
    if protocol.frozen is None:
        raise ValueError("the protocol has no frozen definitions")
    missing = [
        field.name
        for field in fields(protocol.frozen)
        if not getattr(protocol.frozen, field.name)
    ]
    missing += [
        f"the identifier of {name}"
        for name, scenario_id in protocol.frozen.scenario_ids.items()
        if not scenario_id
    ]
    if missing:
        raise ValueError(f"the frozen definitions miss {joined_text(missing)}")
    scenarios = len(protocol.frozen.scenario_ids)
    if protocol.worlds != len(evaluation) * scenarios:
        raise ValueError(
            f"the budget of {protocol.worlds} worlds is not {len(evaluation)} seeds "
            f"times {scenarios} scenarios"
        )


# The refusal of a development run that plays no seed or an evaluation seed.
def check_development_seeds(protocol: CalibrationProtocol, seeds: range) -> None:
    if not seeds:
        raise ValueError(
            "a development run plays at least 1 seed; --stress-seeds is 1 or more"
        )
    if set(seeds) & set(protocol.evaluation_seeds):
        raise ValueError(
            f"a development run plays the seeds {seeds_text(seeds)}, which reach the "
            f"evaluation seeds {seeds_text(protocol.evaluation_seeds)}"
        )


def differing_definitions(
    first: FrozenDefinitions, second: FrozenDefinitions
) -> list[str]:
    return [
        field.name
        for field in fields(first)
        if getattr(first, field.name) != getattr(second, field.name)
    ]


# The refusal of an evaluation by a protocol that `check_protocol` refuses, under
# current definitions that differ from the frozen ones, over an index that holds a run
# of an evaluation seed under another version, code, solver environment, settings or
# scenario identifier, or after a start of an evaluation of one of its seeds under other
# definitions.
def check_evaluation(
    protocol: CalibrationProtocol,
    current: FrozenDefinitions,
    runs: list[PlayedRun],
    starts: list[EvaluationStart],
) -> None:
    check_protocol(protocol)
    assert protocol.frozen is not None
    differing = differing_definitions(current, protocol.frozen)
    if differing:
        raise ValueError(
            "the current definitions differ from the frozen ones in "
            f"{joined_text(differing)}"
        )
    identity = RunIdentity(
        settings=current.settings,
        version=current.version,
        code=current.code,
        solver_environment=current.solver_environment,
    )
    others = [
        run
        for run in runs
        if run.seed in protocol.evaluation_seeds
        and (
            identity_of(run) != identity
            or run.scenario_id not in current.scenario_ids.values()
        )
    ]
    if others:
        raise ValueError(
            "runs of the evaluation seeds under other definitions in the index: "
            f"{len(others)}; a new evaluation takes seeds no run has read"
        )
    for start in starts:
        differing = differing_definitions(start.definitions, current)
        if set(start.seeds) & set(protocol.evaluation_seeds) and differing:
            raise ValueError(
                f"an evaluation of the seeds {seeds_text(start.seeds)} started at "
                f"{start.time} under definitions that differ in "
                f"{joined_text(differing)}; a new evaluation takes seeds no run has "
                "read"
            )


def start_of(entry: dict[str, Any]) -> EvaluationStart:
    return EvaluationStart(
        time=entry["time"],
        seeds=range(entry["first_seed"], entry["last_seed"] + 1),
        definitions=FrozenDefinitions(**entry["definitions"]),
    )


def entry_of(start: EvaluationStart) -> dict[str, Any]:
    return {
        "time": start.time,
        "first_seed": start.seeds[0],
        "last_seed": start.seeds[-1],
        "definitions": asdict(start.definitions),
    }


def read_evaluation_starts(path: Path) -> list[EvaluationStart]:
    if not path.exists():
        return []
    return [start_of(entry) for entry in json.loads(path.read_text())]


# The record of the start of an evaluation: the refusal of an evaluation that
# `check_evaluation` refuses over the index and the starts of the file beside it, then
# its start appended to that file through a new file beside it, so a stop never leaves
# half a file.
def record_evaluation_start(
    index: Path,
    protocol: CalibrationProtocol,
    current: FrozenDefinitions,
    time: str,
) -> None:
    path = index.with_name(EVALUATIONS_FILE)
    starts = read_evaluation_starts(path)
    check_evaluation(protocol, current, read_index(index), starts)
    start = EvaluationStart(
        time=time, seeds=protocol.evaluation_seeds, definitions=current
    )
    new = path.with_name(f"{path.name}.new")
    entries = [entry_of(earlier) for earlier in starts] + [entry_of(start)]
    new.write_text(json.dumps(entries, indent=2) + "\n")
    new.replace(path)


# The line of the protocol in a report: the kind of run, the split of the seeds and,
# for an evaluation, its budget.
def build_protocol_line(protocol: CalibrationProtocol, *, evaluation: bool) -> str:
    split = (
        f"development seeds {seeds_text(protocol.development_seeds)}, evaluation "
        f"seeds {seeds_text(protocol.evaluation_seeds)}"
    )
    if evaluation:
        return (
            f"confirmatory evaluation of the frozen definitions; {split}, a budget of "
            f"{protocol.worlds} worlds"
        )
    return f"development; {split}"
