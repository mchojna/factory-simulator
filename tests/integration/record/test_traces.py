from typing import Any

import pytest
from factories import (
    api_client,
    buy,
    database_file,
    engine_of,
    get,
    post,
    records,
    run_to_the_end,
    start_run,
    submit,
)
from sqlalchemy import event

from factory_simulator.api.record.models.run import Period, Trace


def without_run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key != "run_id"} for row in rows
    ]


@pytest.mark.slow
def test_pending_trace_checks_restart_and_fork_preserve_the_committed_rows():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            run_id = run["id"]
            assert records(client, Trace, run_id=run_id) == []
            before = get(client, f"/runs/{run_id}/observation")
            for _ in range(2):
                assert (
                    post(
                        client, f"/runs/{run_id}/checks", {"period": 1, "decisions": []}
                    )[0]
                    == 200
                )
            assert records(client, Trace, run_id=run_id) == []
            assert submit(client, run_id, 1, [buy("6")])[0] == 200
            prefix = records(client, Trace, run_id=run_id)
            assert len(prefix) == 7
            pending = get(client, f"/runs/{run_id}/observation")
            public = get(client, f"/runs/{run_id}/periods")[1]
            assert "trace" not in str(public)
            assert "tallies" not in str(public)
        with api_client(url) as client:
            assert get(client, f"/runs/{run_id}/observation") == pending
            assert records(client, Trace, run_id=run_id) == prefix
            finished = run_to_the_end(client, run | {"period": 2})
            assert finished["finished"]
            parent = records(client, Trace, run_id=run_id)
            status, fork = post(client, f"/runs/{run_id}/forks", {"period": 2})
            assert status == 201
            assert without_run(
                records(client, Trace, run_id=fork["id"])
            ) == without_run(prefix)
            run_to_the_end(client, fork)
            assert without_run(
                records(client, Trace, run_id=fork["id"])
            ) == without_run(parent)
            assert records(client, Trace, run_id=run_id) == parent
            assert before[1]["period"] == 1


@pytest.mark.slow
def test_a_failed_trace_insert_rolls_back_the_period_and_recovers_the_open_prefix():
    with database_file() as url:
        with api_client(url) as client:
            run = start_run(client)
            run_id = run["id"]
            before = get(client, f"/runs/{run_id}/observation")
            database = engine_of(client)

            def fail_trace_insert(*arguments: object) -> None:
                if str(arguments[2]).startswith("INSERT INTO traces"):
                    raise RuntimeError("interrupted trace transaction")

            event.listen(database, "before_cursor_execute", fail_trace_insert)
            try:
                with pytest.raises(RuntimeError, match="interrupted trace transaction"):
                    submit(client, run_id, 1, [buy("6")])
            finally:
                event.remove(database, "before_cursor_execute", fail_trace_insert)
            assert records(client, Period, run_id=run_id) == []
            assert records(client, Trace, run_id=run_id) == []
            assert get(client, f"/runs/{run_id}/observation") == before
        with api_client(url) as client:
            assert get(client, f"/runs/{run_id}/observation") == before
            assert submit(client, run_id, 1, [buy("6")])[0] == 200
            assert len(records(client, Trace, run_id=run_id)) == 7
