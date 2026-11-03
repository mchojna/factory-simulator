import uuid
from importlib import metadata
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from factory_simulator.api.record import database
from factory_simulator.api.services.examples import EXAMPLES, MANIFEST_FILE
from factory_simulator.api.services.manifests import create_manifest
from factory_simulator.api.services.scenarios import create_scenario

# The identifier of every example manifest and scenario.
FROZEN_IDENTIFIERS: dict[str, str] = {
    "manifest.json": (
        "a91a299d42f9aab32b5f5b4402b76bf3f8d967861c46ba41e55c605ce25152ca"
    ),
    "manifest.json/capacity-cut": (
        "a0719c926a81688c256b776b97ece26e09cd32e30d91dd4d44435388e1e82031"
    ),
    "manifest.json/cash-squeeze": (
        "ab192fc5dab18b24afca999fa306a5769bfab368f047e5391362a6cc9e918df0"
    ),
    "manifest.json/decline": (
        "d554d0316a98ebe75b61890a4d62f8e21642c09b784fa42dc07b5eb1dd94a76e"
    ),
    "manifest.json/demand-step": (
        "1eb5759897af4d65ee08d7204ec0d77450a08f7c6ba8f2f206a21b4887ea49d7"
    ),
    "manifest.json/demand-surge": (
        "cd148b09a5e0bc18fb6e0f8b2399ef3c89d382e9bddf30505ce61ea998130612"
    ),
    "manifest.json/forecasts": (
        "d389df4bd0f58a241a13d1053c5447ba462ea637cb5b36e5b53a73d21e5b9b38"
    ),
    "manifest.json/frequent-breakdowns": (
        "cd43d0d15524e18f1dbbbec3cbc70407d2411f05bf1eb844cb1c4b768a25b35b"
    ),
    "manifest.json/full-warehouse": (
        "80c2a86eac71502d28e2420b203b0711cd0e8fdfce5d492939442c5e4639f13e"
    ),
    "manifest.json/growth": (
        "93ecd6fd6c48d92d1cd5145e46ae242cf506feab8a3c5047c19b1ef37c14734a"
    ),
    "manifest.json/hidden-groups": (
        "a3cc684672e87b582c3cc36cd148cca4ba51b294bd686b074525dea4f467672a"
    ),
    "manifest.json/line-breakdown": (
        "a1ecaedadcde87427d4b0e2a3abf312d521e25279af0e1e789b5d20ec69a9be3"
    ),
    "manifest.json/material-shortage": (
        "94486d34462b193e690f92631cb910df73f6374dcb4be6af6c2c5426d6a9cea4"
    ),
    "manifest.json/notice": (
        "ad2a37815959b94f284dcd28064a33bf0afface4a63d27a54591e8c6f0f3a5ca"
    ),
    "manifest.json/price-change": (
        "c0c520cbc5ef9fd8b3da99d79e1704f6514508843340ca7e8a5c4e9a60de1547"
    ),
    "manifest.json/product-life-cycle": (
        "04e539d2a22e9d91e64f9a7e80ef2eaeb4687434a9ac2dc3dc3250e10de1313e"
    ),
    "manifest.json/quality-crisis": (
        "97f057f3164c8baf8ca238e26a417530a5df2945047d001c298592189227effc"
    ),
    "manifest.json/regional-crisis": (
        "da1e842bd9632f3893d37701bceecde60efb010d5d3ba2139e979720d043c9da"
    ),
    "manifest.json/seasonal-demand": (
        "afe7df932667df7dd4fabd094185a54c9668e2c4c0117814572ef682f4a26c7c"
    ),
    "manifest.json/steady-market": (
        "bf33d4aa015251e29a9675fcd9755ea1f080ebbc4dabc515ff79a708a3ad9ecb"
    ),
    "manifest.json/supplier-outage": (
        "7b6ce5ba06b0905016d6306739e4e5b926d538f142c0577a7c57e3b01a2cbbbb"
    ),
    "manifest.json/surge-and-breakdown": (
        "0d24205bc6556d6f2cf75705a32ba35902b6cc2cdbacdf44c583530dd183a778"
    ),
    "manifest.json/transport-delays": (
        "28b78da4ea2de86e8f2511790ec5102bafb05491ee6457320a095b0b3d8ba493"
    ),
    "manifest.json/yield-drop": (
        "dec60eba65e6a1a2e5c93713f9b2fd518043137351262962bf890b51721d14f7"
    ),
}


# The identifier of the example manifest and of each scenario under it, as the HTTP
# interface stores them.
def example_identifiers() -> dict[str, str]:
    engine = database.create_database_engine(f"duckdb:///:memory:{uuid.uuid4().hex}")
    database.prepare(engine, metadata.version("factory-simulator"))
    found: dict[str, str] = {}
    with Session(engine, expire_on_commit=False) as session:
        body = (EXAMPLES / MANIFEST_FILE).read_bytes()
        _, manifest = create_manifest(session, body)
        manifest_id = cast(dict[str, Any], manifest)["id"]
        found[MANIFEST_FILE] = manifest_id
        for path in sorted((EXAMPLES / "scenarios").glob("*.json")):
            _, scenario = create_scenario(session, manifest_id, path.read_bytes())
            found[f"{MANIFEST_FILE}/{path.stem}"] = cast(dict[str, Any], scenario)["id"]
    engine.dispose()
    return found


@pytest.mark.slow
def test_the_examples_keep_their_frozen_identifiers():
    assert example_identifiers() == FROZEN_IDENTIFIERS
