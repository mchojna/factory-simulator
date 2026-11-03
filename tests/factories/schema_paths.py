import re
from decimal import Decimal
from typing import Any, cast

type Schema = dict[str, Any]

PERIOD_RANGES_REFUSED = (
    "TriangularRange_Annotated_int",
    "NormalRange_Annotated_int",
    "LognormalRange_Annotated_int",
)
# A template shows a lognormal range once, not under every parameter.
LOGNORMAL_RANGES = ("LognormalRange", "LognormalPriceRange")


# Every property path of a JSON schema: `$ref` followed, each variant of a union
# taken, map keys and list positions written as `*`.
def schema_paths(schema: Schema) -> set[str]:
    definitions = cast(dict[str, Schema], schema.get("$defs", {}))
    found: set[str] = set()

    def walk(node: Schema, path: str, seen: frozenset[str]) -> None:
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            # A range of periods is uniform only, so the other ranges of whole
            # numbers are never valid and are not walked.
            if name in seen or name.startswith(
                PERIOD_RANGES_REFUSED + LOGNORMAL_RANGES
            ):
                return
            walk(definitions[name], path, seen | {name})
        for variant in (*node.get("anyOf", []), *node.get("oneOf", [])):
            walk(cast(Schema, variant), path, seen)
        for key, child in cast(dict[str, Schema], node.get("properties", {})).items():
            here = f"{path}.{key}" if path else key
            found.add(here)
            walk(child, here, seen)
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            walk(cast(Schema, extra), f"{path}.*" if path else "*", seen)
        for value in cast(
            dict[str, Schema], node.get("patternProperties", {})
        ).values():
            walk(value, f"{path}.*" if path else "*", seen)
        items = node.get("items")
        if isinstance(items, dict):
            walk(cast(Schema, items), f"{path}.*" if path else "*", seen)

    walk(schema, "", frozenset())
    return found


# Every key path of a JSON document, map keys and list positions written as `*`;
# an object under a key that the schema names is followed by that key.
def document_paths(document: object, map_paths: set[str], path: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for key, child in cast(dict[str, object], document).items():
            name = "*" if path_of(path, "*") in map_paths else key
            here = path_of(path, name)
            found.add(here)
            found |= document_paths(child, map_paths, here)
    elif isinstance(document, list):
        for child in cast(list[object], document):
            found |= document_paths(child, map_paths, path_of(path, "*"))
    return found


# The dotted path of a key below a path, or the key alone below the root.
def path_of(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


# The paths whose keys are map keys, from the `*` entries of schema paths.
def map_paths(paths: set[str]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        parts = path.split(".")
        for position, part in enumerate(parts):
            if part == "*":
                found.add(".".join(parts[: position + 1]))
    return found


# Whether a value read with exact numbers is of a JSON schema type.
def is_of_type(value: object, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if kind == "integer":
        return isinstance(value, int)
    return isinstance(value, int | Decimal)


# The problems of a document read with exact numbers against a JSON schema of the
# OpenAPI document, each `<path>: <problem>`: `$ref`, `anyOf`, `oneOf`, `type`,
# `const`, `enum`, `pattern`, `properties`, `required`, `patternProperties`,
# `additionalProperties` and `items`. A union that no variant passes gives the
# problems of the variant with the fewest.
def schema_errors(
    document: object, schema: Schema, definitions: Schema, path: str = ""
) -> list[str]:
    place = path or "body"
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        return schema_errors(document, definitions[name], definitions, path)
    errors: list[str] = []
    for union in ("anyOf", "oneOf"):
        if union not in schema:
            continue
        found = [
            schema_errors(document, cast(Schema, variant), definitions, path)
            for variant in schema[union]
        ]
        passed = [problems for problems in found if not problems]
        if not passed:
            errors += min(found, key=len)
        elif union == "oneOf" and len(passed) > 1:
            errors.append(f"{place}: passes {len(passed)} variants of oneOf")
    if "type" in schema and not is_of_type(document, schema["type"]):
        return [*errors, f"{place}: is not of type {schema['type']}"]
    if "const" in schema and document != schema["const"]:
        errors.append(f"{place}: is not {schema['const']}")
    if "enum" in schema and document not in schema["enum"]:
        errors.append(f"{place}: is not one of {schema['enum']}")
    pattern = schema.get("pattern")
    if isinstance(document, str) and pattern and re.search(pattern, document) is None:
        errors.append(f"{place}: does not match {pattern}")
    if isinstance(document, dict):
        errors += object_errors(cast(Schema, document), schema, definitions, path)
    items = schema.get("items")
    if isinstance(document, list) and isinstance(items, dict):
        for position, item in enumerate(cast(list[object], document)):
            here = path_of(path, str(position))
            errors += schema_errors(item, cast(Schema, items), definitions, here)
    return errors


# The errors of a JSON object against an object schema: required, unknown and
# invalid keys.
def object_errors(
    document: Schema, schema: Schema, definitions: Schema, path: str
) -> list[str]:
    properties = cast(Schema, schema.get("properties", {}))
    patterns = cast(Schema, schema.get("patternProperties", {}))
    extra = schema.get("additionalProperties", True)
    errors = [
        f"{path_of(path, key)}: Field required"
        for key in schema.get("required", [])
        if key not in document
    ]
    for key, value in document.items():
        here = path_of(path, key)
        matched = [
            cast(Schema, patterns[pattern])
            for pattern in patterns
            if re.search(pattern, key) is not None
        ]
        if key in properties:
            matched = [cast(Schema, properties[key])]
        elif not matched and isinstance(extra, dict):
            matched = [cast(Schema, extra)]
        elif not matched and extra is False:
            errors.append(f"{here}: Extra inputs are not permitted")
        for child in matched:
            errors += schema_errors(value, child, definitions, here)
    return errors
