import pytest
from factories import (
    api_client,
    buy,
    cancel,
    get,
    produce,
    records,
    repair,
    ship,
    start_run,
    submit,
)

from factory_simulator.api.core.json import write_json
from factory_simulator.api.record.models.run import Interaction

QUANTITY_PLACES = "decisions.0.quantity: has more than 3 places"
QUANTITY_ABOVE_0 = "decisions.0.quantity: Input should be greater than 0"


def body_of(period: int, decisions: list[dict[str, object]]) -> bytes:
    return write_json({"period": period, "decisions": decisions})


REFUSALS = [
    (body_of(2, []), 409, "period: is 2, the run is in period 1"),
    (b"\xff\xfe", 422, "body: is not UTF-8"),
    (b"{not json", 422, "body: is not JSON"),
    (body_of(1, [ship("order-1-1", "1.0001")]), 422, QUANTITY_PLACES),
    (body_of(1, [ship("order-1-1", "0.000")]), 422, QUANTITY_ABOVE_0),
    (body_of(1, [ship("order-1-1", "-1.000")]), 422, QUANTITY_ABOVE_0),
    (body_of(1, [produce("monitor", "1.0001")]), 422, QUANTITY_PLACES),
    (body_of(1, [cancel("buy-0-1", "1.0001")]), 422, QUANTITY_PLACES),
    (
        body_of(1, [repair("0.0000")]),
        422,
        "decisions.0.amount: Input should be greater than 0",
    ),
    (
        body_of(1, [repair("0.00001")]),
        422,
        "decisions.0.amount: has more than 4 places",
    ),
    (
        body_of(1, [buy("40", rush=True)]),
        422,
        "decisions.0.rush: Extra inputs are not permitted",
    ),
]


@pytest.mark.parametrize(("body", "status", "detail"), REFUSALS)
def test_a_refused_submission_answers_its_detail_and_leaves_the_period(
    body: bytes, status: int, detail: str
):
    with api_client() as client:
        run = start_run(client)
        response = client.post(f"/api/v1/runs/{run['id']}/decisions", content=body)
        _, read = get(client, f"/runs/{run['id']}")
        rows = records(client, Interaction, run_id=run["id"])
        accepted, _ = submit(client, run["id"], 1, [])

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert read["period"] == 1
    [row] = rows
    assert (row["position"], row["period"], row["kind"]) == (1, 1, "refusal")
    assert (row["refusal"], row["outcomes"]) == (detail, None)
    try:
        written = body.decode()
    except UnicodeDecodeError:
        written = repr(body)
    assert row["submission"] == written
    assert accepted == 200


def test_invalid_unicode_and_a_body_nested_too_deeply_are_kept_refusals():
    lone_surrogate = (
        b'{"period": 1, "decisions": '
        b'[{"kind": "ship", "order": "\\ud800", "quantity": "1"}]}'
    )
    nested = b"[" * 5000 + b"]" * 5000
    with api_client() as client:
        run = start_run(client)
        path = f"/api/v1/runs/{run['id']}"
        submitted = client.post(f"{path}/decisions", content=lone_surrogate)
        checked = client.post(f"{path}/checks", content=lone_surrogate)
        too_deep = client.post(f"{path}/decisions", content=nested)
        _, read = get(client, f"/runs/{run['id']}")
        rows = records(client, Interaction, run_id=run["id"])
        accepted, _ = submit(client, run["id"], 1, [])

    detail = "decisions.0.order: is not valid text"
    assert (submitted.status_code, submitted.json()) == (422, {"detail": detail})
    assert (checked.status_code, checked.json()) == (422, {"detail": detail})
    assert (too_deep.status_code, too_deep.json()) == (
        422,
        {"detail": "body: is nested too deeply"},
    )
    assert read["period"] == 1
    assert [
        (row["kind"], row["refusal"], row["outcomes"], row["submission"])
        for row in rows
    ] == [
        ("refusal", detail, None, lone_surrogate.decode()),
        ("check", detail, None, lone_surrogate.decode()),
        ("refusal", "body: is nested too deeply", None, nested.decode()),
    ]
    assert accepted == 200
