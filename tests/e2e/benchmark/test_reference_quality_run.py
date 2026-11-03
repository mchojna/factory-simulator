from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx2 as httpx
import pytest
from factories import (
    benchmark_client,
    full_warehouse_bodies,
    future_minimum_bodies,
    ordered_transfer_bodies,
    plain_tiny_manifest,
    plain_tiny_scenario,
    play_no_decisions,
    reference_quality_of,
    solver_scale_bodies,
    start_reference,
    start_transfer_order_control,
    unwanted_order_bodies,
)
from stress.playing import (
    World,
    build_solver_environment,
    play_world,
    play_worlds,
    started_server,
)
from stress.report import GAP_RULE, UNSCORABLE_RULE, Provenance, write_report

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.program.solve import GAP_LIMIT


# The world of a future minimum, played as a harness plays it: no decisions, the
# reference and the exact control. The 1.8 by which the program of period 1 of the
# reference, 171.2, exceeds its profit, 169.4, splits into 0.8 of later choices from 0
# to 1 and 1.0 of policy, with no decimal effect, no fitted or dropped decision and no
# solve stopped at a limit. No decisions loses the 4 monitors for 40.
@pytest.mark.slow
def test_the_diagnostic_names_the_policy_gap_apart_from_fitting_and_the_solver():
    manifest, scenario = future_minimum_bodies()
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        quality = reference_quality_of(client, scenario_id, 0)
        periods = benchmark.read_periods(client, quality.reference_run_id)

    assert quality.no_decisions_profit == Decimal(-40)
    assert quality.policy_gap == Decimal("1.0")
    assert quality.future_integrality == pytest.approx(0.8)
    assert quality.decimal_effects == pytest.approx(0)
    assert (quality.fitted, quality.dropped, quality.solves_at_time_limit) == (0, 0, 0)
    assert quality.largest_gap <= GAP_LIMIT
    quantities = [
        [decision["quantity"] for decision in step["submission"]["decisions"]]
        for period in periods
        for step in period["steps"]
        if step["step"] == "make_decisions"
    ]
    assert quantities[:2] == [[], [20]]


# The plain tiny factory from cash 50000000 below 0, no credit, and 12 monitors: no
# decisions loses the 3 orders of 4 monitors for 3 * 4 * 10 = 120 and keeps the
# monitors at 2, so -96; the reference ships 4 monitors a period at 50 less 1 of
# transport, 3 * 4 * 49 = 588, and every buy is out of its reach.
@pytest.mark.slow
def test_the_reference_sells_its_stock_from_far_below_the_credit_line():
    scenario = plain_tiny_scenario()
    scenario["start"] = {"cash": "-50000000", "stock": {"main": {"monitor": "12"}}}
    with benchmark_client() as client:
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        quality = reference_quality_of(client, scenario_id, 0)
        periods = benchmark.read_periods(client, quality.reference_run_id)

    assert quality.no_decisions_profit == Decimal(-96)
    assert quality.reference_profit == Decimal(588)
    assert quality.policy_gap == Decimal(0)
    assert (quality.fitted, quality.dropped, quality.solves_at_time_limit) == (0, 0, 0)
    kinds = [
        decision["kind"]
        for period in periods
        for step in period["steps"]
        if step["step"] == "make_decisions"
        for decision in step["submission"]["decisions"]
    ]
    assert kinds == ["ship"] * 3


# The world of an unwanted starting order, played by the agents of the stress test.
# None of them cancels, so each keeps the 10 chips: 5 paid, 1 of salvage, -4. The
# reference makes what no decisions makes, and the report lists the world as
# unscorable with those profits, beside the rule that a better decision can exist.
@pytest.mark.slow
def test_the_report_lists_a_world_with_a_useful_cancellation_as_unscorable(
    tmp_path: Path,
):
    manifest, scenario = unwanted_order_bodies()
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
        )
        runs, violations = play_world(client, 60.0, "c0de", "c4ec5", world)
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-19T10:00:00",
        command="tests/e2e",
        manifest_name=manifest["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    folder = write_report(
        tmp_path, runs, violations, provenance, datetime(2026, 10, 19)
    )
    report = (folder / "report.md").read_text()

    assert violations == []
    assert {run.profit for run in runs} == {Decimal(-4)}
    section = report.split("## Unscorable worlds\n\n")[1].split("\n\n## ")[0]
    assert section.splitlines()[0] == UNSCORABLE_RULE
    assert section.splitlines()[-1] == (
        "| Plain tiny scenario | 0 | the reference makes no more than no decisions "
        "| -4 | -4 | -4 | full_horizon_optimizer |"
    )


# The world of an ordered transfer with the remote warehouse named `annex`, played by
# the agents of the stress test. Their routes run from annex first, into a main still
# full of chips, so each keeps the board in annex at 100 and earns 0.7 - 100. The
# report lists the world as unscorable, names the order of the routes as a
# restriction of the reference, and calls no better decision impossible, while the
# transfer order control that runs the route from main first earns -0.399.
@pytest.mark.slow
def test_the_report_names_the_order_of_routes_of_an_unscorable_world(tmp_path: Path):
    manifest, scenario = ordered_transfer_bodies("annex")
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
        )
        runs, violations = play_world(client, 60.0, "c0de", "c4ec5", world)
        nothing = next(run for run in runs if run.agent == "no_decisions")
        order = (("main", "buffer"), ("annex", "main"))
        run, control = start_transfer_order_control(
            client, scenario_id, 0, nothing.run_id, order
        )
        result = benchmark.play_run(client, run, control)
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/e2e",
        manifest_name=manifest["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    folder = write_report(
        tmp_path, runs, violations, provenance, datetime(2026, 10, 20)
    )
    report = (folder / "report.md").read_text()

    assert violations == []
    assert {run.profit for run in runs} == {Decimal("-99.3")}
    assert result["profit"] == Decimal("-0.399")
    assert control.fitted == control.dropped == []
    section = report.split("## Unscorable worlds\n\n")[1].split("\n\n## ")[0]
    assert section.splitlines()[0] == UNSCORABLE_RULE
    assert "runs the transfers of a period in the order of its routes" in section
    assert section.splitlines()[-1] == (
        "| Plain tiny scenario | 0 | the reference makes no more than no decisions "
        "| -99.3 | -99.3 | -99.3 | full_horizon_optimizer |"
    )
    assert "impossible" not in report


# The world of a full warehouse with a changeover of 0.5 hours to boards, played by
# the agents of the stress test and by the diagnostic. The program makes 2 boards on
# the line set for them, then 1 monitor, in 3 hours, but the boards find the warehouse
# full. The monitor first frees their space and the boards then need 2.5 hours of the
# 2 left, so the check rejects them: the reference loses the 2 boards and pays a
# changeover its program does not count. It ships 1 monitor in period 2 and 1 in
# period 3 at 49, makes them for 2 + 2 with a changeover of 0.1, loses 1 for 10 and
# keeps 60 chips worth 6: 89.9. Every run passes the checks of the stress test, and
# the diagnostic names the loss those checks do not see.
@pytest.mark.slow
def test_the_diagnostic_names_production_the_reference_loses_to_its_order():
    manifest, scenario = full_warehouse_bodies(board_changeover_time="0.500")
    manifest["lines"]["line-1"]["capacity"] = "3.000"
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
        )
        runs, violations = play_world(client, 60.0, "c0de", "c4ec5", world)
        quality = reference_quality_of(client, scenario_id, 0)

    reference = next(run for run in runs if run.agent == "reference")
    assert violations == []
    assert all(run.violations == () for run in runs)
    assert (reference.profit, reference.dropped, reference.fitted) == (
        Decimal("89.9"),
        1,
        0,
    )
    assert quality.reference_profit == Decimal("89.9")
    assert (quality.dropped, quality.fitted) == (1, 0)
    assert quality.quantity_lost == Decimal(2)
    assert quality.extra_changeovers == 1


# The world of a large selling price, played as the stress test plays it, on a server
# of its own. At a price of 10**18 the HTTP interface accepts the world, and the
# reference stops in the relaxed program of period 1, which counts money in units of
# 10**9, where the chip salvage of 0.1 falls to 1e-10. The index keeps no run of the
# world, and the report names the world, its seed, the agent and the scale. At a price
# of 10**21 a run could reach 10**24, and the HTTP interface refuses the scenario at
# `horizon` before any run.
@pytest.mark.slow
def test_the_report_names_a_world_outside_the_scale_of_the_program(tmp_path: Path):
    manifest, scenario = solver_scale_bodies()
    refused_manifest, refused_scenario = solver_scale_bodies(
        "1000000000000000000000.0000"
    )
    index = tmp_path / "stress-runs.csv"
    with (
        started_server(tmp_path / "stress.duckdb") as url,
        httpx.Client(base_url=url) as client,
    ):
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
        )
        violations = play_worlds(url, [world], 1, 60.0, "c0de", "c4ec5", index)
        other = benchmark.send(client, "POST", "/manifests", refused_manifest)
        other_path = f"/manifests/{other['id']}/scenarios"
        with pytest.raises(RuntimeError) as refused:
            benchmark.send(client, "POST", other_path, refused_scenario)
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/stress",
        manifest_name=manifest["name"],
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    folder = write_report(tmp_path, [], violations, provenance, datetime(2026, 10, 20))
    section = (folder / "report.md").read_text().split("## Violations\n\n")[1]

    assert violations == [
        "Plain tiny scenario seed 0: reference: UnsupportedScaleError: period 1: the "
        "money of the program runs from 0.1 to 1e+18; in units of 1e+09 its smallest "
        "coefficient is 1e-10, at most 1e-09"
    ]
    assert section.startswith(f"- {violations[0]}\n")
    assert not index.exists()
    assert str(refused.value) == (
        f"POST {other_path}: 422 horizon: a run of this scenario can exceed the "
        "numbers the record holds"
    )


# The plain tiny scenario, played as the stress test plays it. Every period buys
# chips, so every program is an integer program, and every solve of the reference
# stops at the gap limit, at no limit of work. The report gives the largest gap of the
# reference, in money, beside the rule that it bounds the program only.
@pytest.mark.slow
def test_the_report_gives_the_gap_of_solves_that_stop_at_the_gap_limit(tmp_path: Path):
    with benchmark_client() as client:
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario = plain_tiny_scenario()
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        world = World(
            scenario=scenario["name"],
            scenario_id=scenario_id,
            manifest_id=stored_manifest["id"],
            scenario_content=scenario,
            seed=0,
            replay=False,
        )
        runs, violations = play_world(client, 60.0, "c0de", "c4ec5", world)
        nothing, _ = play_no_decisions(client, scenario_id, 0)
        run, reference = start_reference(client, scenario_id, 0, nothing["id"])
        benchmark.play_run(client, run, reference)
    provenance = Provenance(
        version="0.5.0",
        code="c0de",
        solver_environment=build_solver_environment(),
        checks="c4ec5",
        analysis="a7a1",
        time="2026-10-20T10:00:00",
        command="tests/e2e",
        manifest_name="Plain tiny factory",
        manifest_id=stored_manifest["id"],
        seeds=range(1),
        protocol="development",
        settings="time_limit=60.0",
    )
    folder = write_report(
        tmp_path, runs, violations, provenance, datetime(2026, 10, 20)
    )
    report = (folder / "report.md").read_text()

    assert violations == []
    assert len(reference.solves) == 3
    assert not any(
        solve.stopped_at_node_limit or solve.stopped_at_time_limit
        for solve in reference.solves
    )
    assert all(0 <= solve.gap <= GAP_LIMIT for solve in reference.solves)
    gap = next(run.largest_gap for run in runs if run.agent == "reference")
    assert gap == max(solve.gap for solve in reference.solves)
    section = report.split("## Scores\n\n")[1].split("\n\n## ")[0]
    assert section.splitlines()[0] == GAP_RULE
    row = next(line for line in section.splitlines() if "| reference |" in line)
    assert row.endswith(f"| {gap:.4f} |")
