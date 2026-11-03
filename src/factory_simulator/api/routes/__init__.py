"""The routes of the HTTP interface: their answer, one module per resource.

Examples:
    >>> answer({"b": 1, "a": 2}).body
    b'{"a":2,"b":1}'
"""

from typing import Any

from fastapi import Response
from pydantic import BaseModel

from factory_simulator.api.core.errors import ErrorPublic
from factory_simulator.api.core.json import write_json


def answer(value: object, status: int = 200) -> Response:
    """Answer a value as canonical JSON.

    Args:
        value (object): The value of the answer.
        status (int, optional): The status; 200 when not given.

    Returns:
        Response: The response with media type `application/json`.

    Examples:
        >>> answer({"cash": 1}, 201).status_code
        201
    """
    return Response(
        write_json(value), status_code=status, media_type="application/json"
    )


def body_schema(model: type[BaseModel]) -> dict[str, object]:
    """Give the OpenAPI body of a route: the schema of its model.

    Args:
        model (type[BaseModel]): The model of the body.

    Returns:
        dict[str, object]: The `openapi_extra` of the route.

    Examples:
        >>> from factory_simulator.api.schemas.run import RunCreate
        >>> content = body_schema(RunCreate)["requestBody"]["content"]
        >>> content["application/json"]
        {'schema': {'$ref': '#/components/schemas/RunCreate'}}
    """
    reference = {"$ref": f"#/components/schemas/{model.__name__}"}
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": reference}},
        }
    }


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Give the OpenAPI error statuses a route answers, each with `ErrorPublic`.

    Every route uses the database, so every route also answers 503.

    Args:
        *statuses (int): The error statuses besides 503, such as 404.

    Returns:
        dict[int | str, dict[str, Any]]: The `responses` of the route.

    Examples:
        >>> sorted(error_responses(404))
        [404, 503]
        >>> error_responses(404)[503]["model"] is ErrorPublic
        True
    """
    return {status: {"model": ErrorPublic} for status in (*statuses, 503)}
