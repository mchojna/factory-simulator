import json

import pytest
from factories import FROZEN_RUNS, frozen_digests, frozen_file


@pytest.mark.slow
@pytest.mark.parametrize(("scenario_name", "seed"), FROZEN_RUNS)
def test_every_frozen_run_replays_to_its_stored_responses_and_rows(
    scenario_name: str, seed: int
):
    stored = json.loads(frozen_file(scenario_name, seed).read_text())

    digests = frozen_digests(scenario_name, seed, stored["decisions"])

    assert digests == {"responses": stored["responses"], "tables": stored["tables"]}


@pytest.mark.slow
def test_the_frozen_run_with_traces_replays_its_complete_trace():
    source = frozen_file("steady-market", 0)
    stored = json.loads((source.parent / "0.5.0" / source.name).read_text())
    digests = frozen_digests(
        "steady-market", 0, stored["decisions"], include_trace=True
    )

    assert digests == {"responses": stored["responses"], "tables": stored["tables"]}
    earlier = json.loads(source.read_text())
    assert stored["responses"] == earlier["responses"]
    assert {
        name: value for name, value in stored["tables"].items() if name != "traces"
    } == earlier["tables"]
