from typing import Any

from factories import tiny_manifest, tiny_scenario, to_engine


def cut(start: int, notice: int) -> dict[str, Any]:
    return {
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": start,
        "duration": 1,
        "strength": "0.5000",
        "notice": notice,
    }


def numbers_in_list_order(*disruptions: dict[str, Any]) -> list[tuple[str, int]]:
    scenario = tiny_scenario() | {"horizon": 10, "disruptions": list(disruptions)}
    _, read = to_engine(tiny_manifest(), scenario)
    return [(disruption.id, disruption.start) for disruption in read.disruptions]


def test_written_disruptions_are_numbered_by_the_period_they_become_visible():
    assert numbers_in_list_order(cut(7, 0), cut(2, 0)) == [
        ("disruption-2", 7),
        ("disruption-1", 2),
    ]
    assert numbers_in_list_order(cut(5, 0), cut(8, 6)) == [
        ("disruption-2", 5),
        ("disruption-1", 8),
    ]
    assert numbers_in_list_order(cut(4, 1), cut(3, 0)) == [
        ("disruption-1", 4),
        ("disruption-2", 3),
    ]
