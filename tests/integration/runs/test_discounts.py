from decimal import Decimal

from factories import (
    api_client,
    discounted_manifest,
    get,
    run_to_the_end,
    start_run,
    submit,
)

SEED = 7
TIER_PRICE = "suppliers.chip-maker.catalogue.chip.discounts.5000.000.price"
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "1200"}


def test_the_tier_is_in_the_public_state_and_not_in_the_observation():
    cancel = {"kind": "cancel", "order": "buy-1-1", "quantity": "300"}
    with api_client() as client:
        run = start_run(client, discounted_manifest())
        _, second = submit(client, run["id"], 1, [BUY])
        _, third = submit(client, run["id"], 2, [cancel])
        _, periods = get(client, f"/runs/{run['id']}/periods")

    [seen] = second["supplier_orders"]
    assert seen["unit_price"] == Decimal("4.6")
    assert "tier" not in seen
    [public] = periods["periods"][0]["steps"][-1]["state"]["supplier_orders"]
    assert public["tier"] == Decimal(1000)
    assert "cancelled" not in public
    [outcome] = third["outcomes"]
    assert (outcome["reason"], outcome["asked"], outcome["available"]) == (
        "below_discount_tier",
        Decimal(300),
        Decimal(200),
    )


def test_a_tier_price_range_is_drawn_from_the_stream_of_its_path():
    price_range = {"min": "4.1000", "max": "4.4000"}
    with api_client() as client:
        run = start_run(client, discounted_manifest(price_range), seed=SEED)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    # The stream of the path gives u = 0.96851646...: 4.1000 + 0.3000 * u = 4.3906.
    assert world["parameters"][TIER_PRICE] == {
        "value": Decimal("4.3906"),
        "origin": "written",
        "drawn": True,
    }


def test_the_description_shows_the_drawn_tier_price_of_the_world():
    price_range = {"min": "4.1000", "max": "4.4000"}
    with api_client() as client:
        run = start_run(client, discounted_manifest(price_range), seed=SEED)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    entry = run["description"]["manifest"]["suppliers"]["chip-maker"]["catalogue"]
    tiers = entry["chip"]["discounts"]
    assert tiers[1] == {"from": 5000, "price": Decimal("4.3906")}
    assert world["parameters"][TIER_PRICE]["value"] == Decimal("4.3906")
