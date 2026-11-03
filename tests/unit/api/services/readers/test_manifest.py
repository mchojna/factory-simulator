from decimal import Decimal
from typing import Any

from factories import tiny_manifest, two_warehouse_manifest

from factory_simulator.api.services.readers.manifest import read_factory


# The manifest of two warehouses with a route from `main` to `centre`; keys given
# replace those of the route.
def with_route(**terms: object) -> dict[str, Any]:
    manifest = two_warehouse_manifest()
    manifest["routes"] = {
        "main": {"centre": {"cost": "0.2000", "lead_time": 1} | terms}
    }
    return manifest


def test_a_manifest_reads_several_warehouses_with_their_factors():
    factory = read_factory(
        two_warehouse_manifest(storage_factor="0.6000", transport_factor="0.8000")
    )

    centre = factory.warehouses["centre"]
    main = factory.warehouses["main"]
    assert (centre.storage_factor, centre.transport_factor) == (
        Decimal("0.6000"),
        Decimal("0.8000"),
    )
    assert centre.accepts == ("products",)
    assert (main.storage_factor, main.transport_factor) == (Decimal(1), Decimal(1))
    assert main.accepts == ("materials", "components", "products")
    assert factory.lines["line-1"].warehouse == "main"


def test_a_manifest_reads_one_way_routes_between_warehouses():
    factory = read_factory(with_route())

    route = factory.routes["main"]["centre"]
    assert (route.cost, route.lead_time) == (Decimal("0.2000"), 1)
    assert "centre" not in factory.routes or "main" not in factory.routes["centre"]


def test_an_item_with_one_recipe_gets_it_as_its_default():
    factory = read_factory(tiny_manifest())

    assert factory.components["board"].default_recipe == "standard"
    assert factory.products["monitor"].default_recipe == "standard"
