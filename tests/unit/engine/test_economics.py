import copy
from decimal import Decimal
from typing import Any, cast

import pytest

from factory_simulator.engine import (
    InputError,
    build_economic_profile,
    generate_manifest,
)

# At seed 2 the one product of these counts takes component-2 (4 materials) and
# component-3 (3 materials), from one supplier for one customer.
FOUR_COMPONENT_COUNTS = {
    "materials": 4,
    "components": 4,
    "products": 1,
    "suppliers": 1,
    "customers": 1,
    "lines": 1,
}


def test_the_four_component_factory_costs_more_to_make_than_serving_a_unit_is_worth():
    profile = build_economic_profile(generate_manifest(FOUR_COMPONENT_COUNTS, 2))

    (pair,) = profile.customer_products
    # component-2: 30.2342 + 37.4440 + 39.2383 + 10.8230 + 6.7699 = 124.5094;
    # component-3: 30.2342 + 37.4440 + 10.8230 + 5.3565 = 83.8577;
    # product-1: 124.5094 + 83.8577 + 4.8067 = 213.1738.
    assert pair.lowest_cost == Decimal("213.1738")
    # 135.7070 - 3.5219 - 213.1738 = -80.9887.
    assert pair.best_margin == Decimal("-80.9887")
    # 135.7070 - 3.5219 + 22.5029 + 4 * 6.2486 = 179.6824.
    assert pair.service_value == Decimal("179.6824")
    assert profile.useful_demand_coverage == Decimal("0.0000")
    # -80.9887 / 135.7070 = -0.596791.
    assert profile.margin_share == Decimal("-0.5968")
    assert profile.economic_class == "unproductive"


def test_a_factory_of_one_material_earns_a_margin_on_every_unit():
    counts = dict.fromkeys(FOUR_COMPONENT_COUNTS, 1)

    profile = build_economic_profile(generate_manifest(counts, 0))

    (pair,) = profile.customer_products
    # 16.7208 + 8.4857 + 10.1711 = 35.3776, and 120.5180 - 3.1174 - 35.3776 = 82.0230.
    assert (pair.lowest_cost, pair.best_margin) == (
        Decimal("35.3776"),
        Decimal("82.0230"),
    )
    # 120.5180 - 3.1174 + 20.2889 + 3 * 9.1909 = 165.2622; (23.904 + 78.536) / 2.
    assert (pair.service_value, pair.demand) == (Decimal("165.2622"), Decimal("51.220"))
    assert profile.useful_demand_coverage == Decimal("1.0000")
    # 82.0230 / 120.5180 = 0.680595.
    assert profile.margin_share == Decimal("0.6806")
    assert profile.economic_class == "profitable"


def test_a_unit_sold_below_its_cost_is_still_worth_serving_for_its_penalties():
    profile = build_economic_profile(generate_manifest(FOUR_COMPONENT_COUNTS, 1))

    (pair,) = profile.customer_products
    # Materials 38.4168 + 40.3655 + 2.3147 + 0.5896 = 81.6866; component-3 adds 9.1103
    # and component-4 6.1388: 90.7969 + 87.8254 + 4.8475 = 183.4698.
    assert pair.lowest_cost == Decimal("183.4698")
    # 153.4906 - 2.9225 - 183.4698 = -32.9017, but 153.4906 - 2.9225 + 20.6403
    # + 4 * 10.4158 = 212.8716 is above the cost.
    assert (pair.best_margin, pair.service_value) == (
        Decimal("-32.9017"),
        Decimal("212.8716"),
    )
    assert profile.useful_demand_coverage == Decimal("1.0000")
    # -32.9017 / 153.4906 = -0.214357.
    assert profile.margin_share == Decimal("-0.2144")
    assert profile.economic_class == "penalty-driven"


def test_the_margin_share_weights_each_customer_product_by_its_middle_demand():
    counts = {
        "materials": 4,
        "components": 3,
        "products": 2,
        "suppliers": 2,
        "customers": 2,
        "lines": 2,
    }

    profile = build_economic_profile(generate_manifest(counts, 0))

    # product-1 = (39.4311 + 8.4857) + (16.7208 + 21.6463 + 10.8826)
    # + (21.6463 + 6.8599) + 6.8010 = 132.4737; product-2 = 47.9168 + 7.3307.
    assert [
        (pair.customer, pair.product, pair.best_margin)
        for pair in profile.customer_products
    ] == [
        ("customer-1", "product-1", Decimal("-15.0731")),
        ("customer-2", "product-1", Decimal("29.4121")),
        ("customer-2", "product-2", Decimal("135.4269")),
    ]
    # (-15.0731 * 51.220 + 29.4121 * 53.191 + 135.4269 * 33.726)
    # / (120.5180 * 51.220 + 165.9913 * 53.191 + 193.0771 * 33.726)
    # = 5359.8224585 / 21513.8934729 = 0.249133.
    assert profile.margin_share == Decimal("0.2491")
    assert profile.economic_class == "profitable"


def test_a_second_product_beside_the_first_covers_only_its_own_demand():
    profile = build_economic_profile(
        generate_manifest(FOUR_COMPONENT_COUNTS | {"products": 2}, 2)
    )

    first, second = profile.customer_products
    assert (first.lowest_cost, first.service_value) == (
        Decimal("213.1738"),
        Decimal("179.6824"),
    )
    # product-2 is made of the same components: 124.5094 + 83.8577 + 9.1155; a unit
    # is worth 191.9103 - 3.6033 + 21.8705 + 2 * 9.2783 = 228.7341, so 52.512 of the
    # 57.070 + 52.512 units of middle demand are useful: 0.479203.
    assert (second.lowest_cost, second.service_value) == (
        Decimal("217.4826"),
        Decimal("228.7341"),
    )
    assert profile.useful_demand_coverage == Decimal("0.4792")
    assert profile.economic_class == "penalty-driven"


def test_an_item_made_on_two_lines_costs_its_cheaper_line():
    manifest = cast(
        dict[str, Any], generate_manifest(dict.fromkeys(FOUR_COMPONENT_COUNTS, 1), 0)
    )
    second = copy.deepcopy(manifest["lines"]["line-1"])
    second["items"] = {"product-1": second["items"]["product-1"] | {"cost": "20.1711"}}
    manifest["lines"]["line-2"] = second

    profile = build_economic_profile(manifest)

    # line-1 makes product-1 for 10.1711 and line-2 for 20.1711:
    # 16.7208 + 8.4857 + 10.1711 = 35.3776.
    (pair,) = profile.customer_products
    assert pair.lowest_cost == Decimal("35.3776")


def test_a_material_that_no_supplier_sells_is_refused():
    manifest = cast(
        dict[str, Any], generate_manifest(dict.fromkeys(FOUR_COMPONENT_COUNTS, 1), 0)
    )
    manifest["suppliers"]["supplier-1"]["catalogue"] = {}

    with pytest.raises(
        InputError, match=r"^materials\.material-1: is in no catalogue$"
    ):
        build_economic_profile(manifest)


def test_a_manifest_without_customers_has_no_share_of_demand_or_margin():
    manifest = generate_manifest(dict.fromkeys(FOUR_COMPONENT_COUNTS, 1), 0)
    manifest["customers"] = {}

    profile = build_economic_profile(manifest)

    assert profile.customer_products == ()
    assert (profile.useful_demand_coverage, profile.margin_share) == (
        Decimal("0.0000"),
        Decimal("0.0000"),
    )
    assert profile.economic_class == "unproductive"
