from collections.abc import Callable
from typing import Any

import pytest
from factories import (
    api_client,
    changeover_manifest,
    discounted_manifest,
    get,
    post,
    start_run,
)


@pytest.mark.parametrize("manifest_of", [changeover_manifest, discounted_manifest])
def test_a_manifest_with_changeovers_or_discounts_is_not_linear(
    manifest_of: Callable[[], dict[str, Any]],
):
    with api_client() as client:
        _, created = post(client, "/manifests", manifest_of())
        _, manifest = get(client, f"/manifests/{created['id']}")
        run = start_run(client, manifest_of())

    assert manifest["linear"] is False
    assert run["description"]["linear"] is False
