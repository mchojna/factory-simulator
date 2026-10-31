# Writes the frozen runs of the example manifest. Run it from the root with
# `PYTHONPATH=tests uv run python tests/frozen/write_frozen_runs.py`
# when the rules or the frozen inputs change in a new version.

import json

from factories import FROZEN_RUNS, frozen_decisions, frozen_digests, frozen_file


def write_frozen_runs() -> None:
    for scenario_name, seed in FROZEN_RUNS:
        decisions = frozen_decisions(scenario_name, seed)
        digests = frozen_digests(scenario_name, seed, decisions)
        stored = {"decisions": decisions} | digests
        path = frozen_file(scenario_name, seed)
        path.write_text(json.dumps(stored, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    write_frozen_runs()
