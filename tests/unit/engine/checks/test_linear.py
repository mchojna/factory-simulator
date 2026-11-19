from factories import tiny_manifest

from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.engine import is_linear


def test_a_manifest_with_a_min_quantity_or_discounts_is_not_linear():
    manifest = tiny_manifest()
    linear = read_factory(manifest)
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["min_quantity"] = "10.000"
    with_minimum = read_factory(manifest)
    del entry["min_quantity"]
    entry["discounts"] = [{"from": "100.000", "price": "0.4000"}]
    with_discounts = read_factory(manifest)

    assert is_linear(linear)
    assert not is_linear(with_minimum)
    assert not is_linear(with_discounts)


def test_a_manifest_with_a_changeover_is_not_linear():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["board"]["changeover_time"] = "1.000"

    assert not is_linear(read_factory(manifest))
