from decimal import Decimal

from factories import draw_world_of_bodies, tiny_manifest, tiny_scenario

from factory_simulator.engine.decisions.plant import Plant, repair_hours_left


def test_a_repair_has_the_regular_hours_left_after_production_changeover_and_repair():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["capacity"] = "40.000"
    world = draw_world_of_bodies(manifest, tiny_scenario())
    plant = Plant(
        period=1,
        stock={},
        customer_orders={},
        receivables=[],
        condition={"line-1": Decimal(1)},
        set_for={},
        hours={"line-1": Decimal(10)},
        changeover_hours={"line-1": Decimal(2)},
        overtime_hours={},
        repair_hours={"line-1": Decimal(3)},
        repairs={},
        production=[],
        plans=[],
        supplier_orders=[],
        transfers=[],
    )
    assert repair_hours_left("line-1", plant, world) == Decimal("25.000")
