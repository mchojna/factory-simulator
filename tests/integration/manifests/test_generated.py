import pytest
from factories import (
    api_client,
    get,
    post,
)

COUNTS = {
    "materials": 4,
    "components": 3,
    "products": 2,
    "suppliers": 2,
    "customers": 2,
    "lines": 2,
}


def test_the_same_counts_and_seed_store_one_manifest_and_another_seed_another():
    with api_client() as client:
        first_status, first = post(
            client, "/manifests/generated", {"counts": COUNTS, "seed": 0}
        )
        second_status, second = post(
            client, "/manifests/generated", {"counts": COUNTS, "seed": 0}
        )
        _, other = post(client, "/manifests/generated", {"counts": COUNTS, "seed": 1})

    assert (first_status, second_status) == (201, 200)
    assert first["id"] == second["id"]
    assert other["id"] != first["id"]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (0, "counts.lines: Input should be greater than or equal to 1"),
        (6, "counts.lines: is above components + products"),
    ],
)
def test_counts_out_of_bounds_are_refused_at_their_count(lines: int, message: str):
    with api_client() as client:
        response = client.post(
            "/api/v1/manifests/generated",
            json={"counts": COUNTS | {"lines": lines}, "seed": 0},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == message


def test_a_generated_manifest_holds_the_counted_objects_and_is_linear():
    with api_client() as client:
        _, created = post(client, "/manifests/generated", {"counts": COUNTS, "seed": 0})
        status, manifest = get(client, f"/manifests/{created['id']}")

    content = manifest["content"]
    assert status == 200
    assert manifest["linear"] is True
    for kind, count in COUNTS.items():
        assert len(content[kind]) == count


def test_counts_sent_as_text_generate_the_manifest_of_the_same_numbers():
    numbers = dict(zip(COUNTS, (2, 2, 2, 1, 1, 1), strict=True))
    texts = {kind: str(count) for kind, count in numbers.items()}
    with api_client() as client:
        status, from_texts = post(
            client, "/manifests/generated", {"counts": texts, "seed": 0}
        )
        _, from_numbers = post(
            client, "/manifests/generated", {"counts": numbers, "seed": 0}
        )

    assert status == 201
    assert from_texts["id"] == from_numbers["id"]


def test_the_matched_economy_stores_another_manifest_that_names_its_prices():
    with api_client() as client:
        _, unrestricted = post(
            client,
            "/manifests/generated",
            {"counts": COUNTS, "seed": 0, "economy": "unrestricted"},
        )
        _, default = post(client, "/manifests/generated", {"counts": COUNTS, "seed": 0})
        status, matched = post(
            client,
            "/manifests/generated",
            {"counts": COUNTS, "seed": 0, "economy": "matched"},
        )

    assert status == 201
    assert unrestricted["id"] == default["id"] != matched["id"]
    assert matched["content"]["description"] == (
        "Generated from 4 materials, 3 components, 2 products, 2 suppliers, "
        "2 customers, 2 lines with seed 0 and matched prices."
    )


def test_an_unknown_economy_is_refused_at_its_key():
    with api_client() as client:
        response = client.post(
            "/api/v1/manifests/generated",
            json={"counts": COUNTS, "seed": 0, "economy": "profitable"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "economy: Input should be 'unrestricted' or 'matched'"
    )
