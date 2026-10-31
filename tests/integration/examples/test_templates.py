from decimal import Decimal

from factories import api_client, get, post, run_to_the_end

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES

TEMPLATES = EXAMPLES / "templates"


def template(name: str) -> object:
    return read_json_bytes((TEMPLATES / name).read_bytes())


def test_the_templates_are_created_and_their_run_balances():
    with api_client() as client:
        manifest_status, manifest = post(
            client, "/manifests", template("manifest.json")
        )
        path = f"/manifests/{manifest['id']}/scenarios"
        scenario_status, scenario = post(client, path, template("scenario.json"))
        _, run = post(client, "/runs", {"scenario_id": scenario["id"], "seed": 0})
        finished = run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    assert (manifest_status, scenario_status) == (201, 201)
    assert finished["finished"] is True
    assert len(periods["periods"]) == 12
    ledger = [
        row["amount"] for period in periods["periods"] for row in period["ledger"]
    ]
    assert sum(ledger, Decimal(0)) == result["cash_at_end"] - result["cash_at_start"]
