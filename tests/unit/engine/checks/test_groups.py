from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

import pytest
from factories import tiny_manifest, tiny_scenario, to_engine

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.engine import (
    Factory,
    Group,
    InputError,
    Warehouse,
    check_factory,
)


def tiny_factory() -> Factory:
    return to_engine(tiny_manifest(), tiny_scenario())[0]


def with_supplier_groups(factory: Factory, *group_ids: str) -> Factory:
    supplier = replace(factory.suppliers["chip-maker"], groups=group_ids)
    return replace(factory, suppliers=MappingProxyType({"chip-maker": supplier}))


def with_customer_groups(factory: Factory, *group_ids: str) -> Factory:
    customer = replace(factory.customers["distributor"], groups=group_ids)
    return replace(factory, customers=MappingProxyType({"distributor": customer}))


def with_groups(factory: Factory, **groups: Group) -> Factory:
    return replace(factory, groups=MappingProxyType(groups))


def region() -> Group:
    return Group(kind="region", members=("chip-maker",), member_type="suppliers")


def refusal_message(factory: Factory) -> str:
    with pytest.raises(InputError) as refusal:
        check_factory(factory)
    return str(refusal.value)


def test_the_tiny_factory_passes():
    check_factory(tiny_factory())


def test_a_group_named_by_a_reserved_word_is_refused():
    factory = with_supplier_groups(tiny_factory(), "materials")
    factory = with_groups(factory, materials=region())
    assert refusal_message(factory) == "groups.materials: is a reserved word"


def test_a_group_of_kind_customer_is_refused():
    factory = with_supplier_groups(tiny_factory(), "east")
    east = Group(kind="customer", members=("chip-maker",), member_type="suppliers")
    factory = with_groups(factory, east=east)
    assert refusal_message(factory) == "groups.east.kind: may not be customer"


def test_a_member_listing_a_group_that_does_not_exist_is_refused():
    factory = with_supplier_groups(tiny_factory(), "apac")
    assert refusal_message(factory) == "suppliers.chip-maker.groups.0: names no group"


def test_a_member_in_two_groups_of_one_kind_is_refused():
    factory = with_supplier_groups(tiny_factory(), "apac", "emea")
    factory = with_groups(factory, apac=region(), emea=region())
    assert refusal_message(factory) == (
        "suppliers.chip-maker.groups.1: a second group of kind region"
    )


def test_a_group_with_members_of_two_types_is_refused():
    factory = with_supplier_groups(tiny_factory(), "apac")
    factory = with_customer_groups(factory, "apac")
    factory = with_groups(factory, apac=region())
    assert refusal_message(factory) == "groups.apac: has members of two types"


def test_a_group_with_no_members_is_refused():
    spare = Group(kind="region", members=(), member_type="")
    factory = with_groups(tiny_factory(), spare=spare)
    assert refusal_message(factory) == "groups.spare: has no members"


def test_a_group_giving_defaults_under_a_key_its_members_do_not_use_is_refused():
    factory = with_supplier_groups(tiny_factory(), "apac")
    apac = replace(region(), defaults_keys=("lines",))
    factory = with_groups(factory, apac=apac)
    assert (
        refusal_message(factory)
        == "groups.apac.defaults.lines: is not used by suppliers"
    )


def test_a_warehouse_accepting_a_group_that_holds_no_items_is_refused():
    factory = with_supplier_groups(tiny_factory(), "apac")
    factory = with_groups(factory, apac=region())
    main = Warehouse(
        capacity=Decimal("1000.000"),
        accepts=("products",),
        accepted_groups=("apac",),
        accepted_group_positions=(1,),
    )
    factory = replace(factory, warehouses=MappingProxyType({"main": main}))
    assert refusal_message(factory) == (
        "warehouses.main.accepts.1.group: names no group of items"
    )


# The group `chips` holds items and takes the one position; `apac` holds suppliers.
def test_a_warehouse_with_fewer_positions_than_accepted_groups_raises_a_zip_error():
    factory = with_supplier_groups(tiny_factory(), "apac")
    chip = replace(factory.materials["chip"], groups=("chips",))
    factory = replace(factory, materials=MappingProxyType({"chip": chip}))
    chips = Group(kind="category", members=("chip",), member_type="materials")
    factory = with_groups(factory, apac=region(), chips=chips)
    main = Warehouse(
        capacity=Decimal("1000.000"),
        accepts=("materials", "components", "products"),
        accepted_groups=("chips", "apac"),
        accepted_group_positions=(3,),
    )
    factory = replace(factory, warehouses=MappingProxyType({"main": main}))

    with pytest.raises(ValueError, match="zip"):
        check_factory(factory)


def test_the_example_manifest_with_its_groups_passes():
    check_factory(
        read_factory(read_json_bytes((EXAMPLES / "manifest.json").read_bytes()))
    )
