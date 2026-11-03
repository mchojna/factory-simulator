"""The groups of a manifest: the values they give their members.

Examples:
    >>> objects_of({"lines": {"smt": {}}}, "lines")
    {'smt': {}}
"""

import copy
from typing import Any, cast

from factory_simulator.api.core.numbers import validate
from factory_simulator.api.schemas.manifest import ManifestGroups

ITEM_TYPES = ("materials", "components", "products")

type Document = dict[str, Any]


def resolve_groups(document: object) -> tuple[object, dict[str, str]]:
    """Resolve groups: give the defaults of the groups of a manifest to its members.

    A member takes, for every parameter it leaves out, the value of the first of its
    groups that gives it, in the order the member lists them. A catalogue entry asks
    the supplier's groups first, then the material's; a customer product the
    customer's, then the product's; a line item the line's, then the item's.

    A listed group that does not exist gives nothing; the checks of the factory
    refuse it.

    Args:
        document (object): The manifest as read by `read_json_bytes`.

    Returns:
        tuple[object, dict[str, str]]: The manifest with the values of groups
            written into their members, and the group each such value came from, by
            the path of the parameter.

    Raises:
        InputError: If a value of a group breaks the model, at that value.

    Examples:
        >>> manifest, given = resolve_groups(
        ...     {
        ...         "materials": {"chip": {"groups": ["chips"]}},
        ...         "groups": {
        ...             "chips": {
        ...                 "kind": "type",
        ...                 "defaults": {"items": {"space": "0.001"}},
        ...             }
        ...         },
        ...     }
        ... )
        >>> manifest["materials"]["chip"]["space"], given
        ('0.001', {'materials.chip.space': 'chips'})
    """
    if not isinstance(document, dict):
        return document, {}
    manifest = copy.deepcopy(cast(Document, document))
    if "groups" not in manifest:
        return manifest, {}
    validate(ManifestGroups, {"groups": manifest["groups"]})
    return manifest, give_defaults(
        manifest, cast(dict[str, Document], manifest["groups"])
    )


def give_defaults(manifest: Document, groups: dict[str, Document]) -> dict[str, str]:
    """Give the defaults of groups to every member that leaves a value out.

    Args:
        manifest (dict[str, Any]): The manifest, changed in place.
        groups (dict[str, dict[str, Any]]): The groups by identifier.

    Returns:
        dict[str, str]: The group each written value came from, by the path of the
            parameter.

    Examples:
        >>> manifest = {"materials": {"chip": {"groups": ["chips"]}}}
        >>> groups = {"chips": {"defaults": {"items": {"space": "0.001"}}}}
        >>> give_defaults(manifest, groups)
        {'materials.chip.space': 'chips'}
        >>> manifest["materials"]["chip"]["space"]
        '0.001'
    """
    given: dict[str, str] = {}

    def listed(member_type: str, object_id: str) -> list[str]:
        # An entry that is not text gives nothing; the model refuses it later.
        member = objects_of(manifest, member_type).get(object_id, {})
        entries = member.get("groups", [])
        if not isinstance(entries, list):
            return []
        return [
            entry for entry in cast(list[object], entries) if isinstance(entry, str)
        ]

    def fill(target: object, path: str, group_ids: list[str], key: str) -> None:
        if not isinstance(target, dict):
            return
        target = cast(Document, target)
        for group_id in group_ids:
            if group_id not in groups:
                continue
            defaults = cast(Document, groups[group_id].get("defaults") or {})
            for name, value in cast(Document, defaults.get(key) or {}).items():
                if name not in target:
                    target[name] = copy.deepcopy(value)
                    given[f"{path}.{name}"] = group_id

    item_type = {
        item_id: member_type
        for member_type in ITEM_TYPES
        for item_id in objects_of(manifest, member_type)
    }
    for member_type in ITEM_TYPES:
        for item_id, item in objects_of(manifest, member_type).items():
            fill(
                item, f"{member_type}.{item_id}", listed(member_type, item_id), "items"
            )
    for supplier_id, supplier in objects_of(manifest, "suppliers").items():
        for material_id, entry in objects_of(supplier, "catalogue").items():
            group_ids = listed("suppliers", supplier_id)
            if material_id in item_type:
                group_ids += listed(item_type[material_id], material_id)
            path = f"suppliers.{supplier_id}.catalogue.{material_id}"
            fill(entry, path, group_ids, "catalogue")
    for customer_id, customer in objects_of(manifest, "customers").items():
        group_ids = listed("customers", customer_id)
        fill(customer, f"customers.{customer_id}", group_ids, "customers")
        for product_id, terms in objects_of(customer, "products").items():
            terms_group_ids = list(group_ids)
            if product_id in item_type:
                terms_group_ids += listed(item_type[product_id], product_id)
            path = f"customers.{customer_id}.products.{product_id}"
            fill(terms, path, terms_group_ids, "customer_products")
    for line_id, line in objects_of(manifest, "lines").items():
        group_ids = listed("lines", line_id)
        fill(line, f"lines.{line_id}", group_ids, "lines")
        for item_id, terms in objects_of(line, "items").items():
            terms_group_ids = list(group_ids)
            if item_id in item_type:
                terms_group_ids += listed(item_type[item_id], item_id)
            path = f"lines.{line_id}.items.{item_id}"
            fill(terms, path, terms_group_ids, "line_items")
    return given


def objects_of(document: Document, key: str) -> dict[str, Document]:
    """Give the objects under a key that are written as JSON objects.

    The model of the manifest refuses anything else later, at its own path.

    Args:
        document (dict[str, Any]): A part of the manifest.
        key (str): The key of a mapping of objects.

    Returns:
        dict[str, dict[str, Any]]: The objects by identifier.

    Examples:
        >>> objects_of({"lines": {"smt": {}, "broken": 1}}, "lines")
        {'smt': {}}
    """
    mapping = document.get(key)
    if not isinstance(mapping, dict):
        return {}
    return {
        object_id: cast(Document, member)
        for object_id, member in cast(Document, mapping).items()
        if isinstance(member, dict)
    }
