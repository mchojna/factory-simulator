from factories import api_client, records, run_to_the_end, start_run

from factory_simulator.api.record.models.run import (
    Event,
    Interaction,
    LedgerEntry,
    Measure,
    Outcome,
    Period,
    Result,
    Run,
    World,
)


def test_a_whole_run_fills_every_table_of_the_run():
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run, {1: [ship]})
        counts = {
            table.__tablename__: len(records(client, table, run_id=run["id"]))
            for table in (World, Result, Period, Event, LedgerEntry, Outcome, Measure)
        }
        counts["runs"] = len(records(client, Run, id=run["id"]))
        counts["interactions"] = len(records(client, Interaction, run_id=run["id"]))
        periods = [row["period"] for row in records(client, Period, run_id=run["id"])]

    assert {name: counts[name] for name in ("runs", "worlds", "results")} == {
        "runs": 1,
        "worlds": 1,
        "results": 1,
    }
    assert periods == [1, 2, 3, 4, 5]
    # Events: 15 storage of 3 items in 5 periods, 5 new orders, 5 interest, 3 late
    # penalties of the orders of periods 2 to 4 and 4 lost sales of the orders of
    # periods 2 to 5. Ledger: 15 storage, 5 interest earned, 3 late penalties, 4
    # lost-sale penalties, and the payment and transport of the ship.
    assert (counts["events"], counts["ledger"], counts["outcomes"]) == (32, 29, 1)
    assert counts["measures"] > 0
    assert counts["interactions"] == 0
