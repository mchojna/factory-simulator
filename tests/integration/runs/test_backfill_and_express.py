from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    example_bodies,
    get,
    records,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.record.models.run import Period

BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "100"}


def backfill_bodies(
    disruptions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        lead_time=2,
        punctuality="0.0000",
        delay=1,
        completeness="0.9000",
        acceptance="0.9800",
        backfill_delay=2,
    )
    scenario = tiny_scenario()
    scenario["horizon"] = 8
    scenario["disruptions"] = disruptions or []
    return manifest, scenario


def measures_of_period(periods: dict[str, Any], period: int) -> dict[str, Any]:
    return periods["periods"][period - 1]["steps"][-1]["measures"]


def test_the_backfill_period_stays_private_and_the_backfill_is_an_event():
    with api_client() as client:
        run = start_run(client, *backfill_bodies())
        observations: dict[int, Any] = {}
        for period in range(1, 7):
            decisions = [BUY] if period == 2 else []
            _, observations[period + 1] = submit(client, run["id"], period, decisions)
        run_to_the_end(client, run | {"period": 7})
        _, periods = get(client, f"/runs/{run['id']}/periods")
        fifth = records(client, Period, run_id=run["id"], period=5)[0]

    [order] = observations[6]["supplier_orders"]
    assert (order["id"], order["open_quantity"], order["expected_arrival"]) == (
        "buy-2-1",
        Decimal(10),
        4,
    )
    assert "backfill" not in order
    receive = periods["periods"][6]["steps"][0]
    assert receive["events"] == [
        {
            "kind": "delivery",
            "step": "receive_deliveries",
            "reference": "buy-2-1",
            "ordered": Decimal(10),
            "arrived": Decimal(10),
            "accepted": Decimal("9.8"),
            "lost": Decimal(0),
            "payment": Decimal("4.9"),
            "backfill": True,
        }
    ]
    assert fifth["private"] == {
        "supplier_orders": {"buy-2-1": {"arrival": 5, "backfill": 7}}
    }


def test_an_express_buy_without_express_terms_is_rejected():
    with api_client() as client:
        run = start_run(client)
        status, observation = submit(client, run["id"], 1, [BUY | {"express": True}])

    assert status == 200
    [outcome] = observation["outcomes"]
    assert (outcome["accepted"], outcome["reason"]) == (False, "no_express")
    assert "asked" not in outcome


def test_the_measures_count_backfill_units_as_late_and_outage_losses_as_lost():
    outage = {
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": 5,
        "duration": 1,
        "strength": "0.5000",
    }
    supplier = "chip-maker/chip"
    with api_client() as client:
        late_run = start_run(client, *backfill_bodies())
        run_to_the_end(client, late_run, {2: [BUY]})
        _, late = get(client, f"/runs/{late_run['id']}/periods")
        outage_run = start_run(client, *backfill_bodies([outage]))
        run_to_the_end(client, outage_run, {2: [BUY]})
        _, lost = get(client, f"/runs/{outage_run['id']}/periods")

    late_in_7 = measures_of_period(late, 7)["suppliers"][supplier]
    lost_in_5 = measures_of_period(lost, 5)["suppliers"][supplier]
    assert late_in_7["units_arrived_late"] == Decimal(10)
    assert lost_in_5["units_lost_in_delivery"] == Decimal(45)


# The passive kit of emea-electronic-parts in the steady market with seed 0, with the
# groups of punctuality, delay, completeness and acceptance hidden: lead time 2,
# express lead time 1, price 2.4332 and express cost 0.6000. A normal buy and an
# express buy of 1.000 are placed in period 1.
def test_an_express_order_shows_its_own_outcome_with_the_outcome_groups_hidden():
    manifest, scenario = example_bodies("steady-market")
    scenario["hidden"] = [
        f"suppliers.catalogue.{key}"
        for key in ("punctuality", "delay", "completeness", "acceptance")
    ]
    kit = {
        "kind": "buy",
        "supplier": "emea-electronic-parts",
        "material": "passive-kit",
        "quantity": "1.000",
        "warehouse": "main-plant",
    }
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=0)
        _, second = submit(client, run["id"], 1, [kit, kit | {"express": True}])
        _, third = submit(client, run["id"], 2, [])

    shown = run["description"]["manifest"]["suppliers"]["emea-electronic-parts"]
    assert "completeness" not in shown["catalogue"]["passive-kit"]
    # The express order arrives first with its own outcome: completeness 0.9616 sends
    # 0.962 and acceptance 0.9871 accepts 0.950, paid at 3.0332. The normal order
    # stays open with its expected arrival, and the express order waits for its
    # backfill.
    deliveries = [event for event in second["events"] if event["kind"] == "delivery"]
    assert [
        (event["reference"], event["arrived"], event["accepted"], event["payment"])
        for event in deliveries
    ] == [("buy-1-2", Decimal("0.962"), Decimal("0.95"), Decimal("2.88154"))]
    open_orders = [
        (order["id"], order["open_quantity"], order["expected_arrival"])
        for order in second["supplier_orders"]
        if order["supplier"] == "emea-electronic-parts"
    ]
    assert open_orders == [
        ("buy-1-1", Decimal(1), 3),
        ("buy-1-2", Decimal("0.038"), 2),
    ]
    # The normal order brings the outcome of normal orders: completeness 0.9657 sends
    # 0.966 and acceptance 0.9894 accepts 0.956, paid at 2.4332.
    deliveries = [event for event in third["events"] if event["kind"] == "delivery"]
    assert [
        (event["reference"], event["arrived"], event["accepted"], event["backfill"])
        for event in deliveries
    ] == [
        ("buy-1-1", Decimal("0.966"), Decimal("0.956"), False),
        ("buy-1-2", Decimal("0.038"), Decimal("0.038"), True),
    ]
